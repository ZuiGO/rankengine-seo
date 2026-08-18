"""Agent runtime: the planner -> executor loop with checkpoints, budgets,
loop guards, and episode persistence."""

import json
import time
from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.models.agent_schemas import AgentDecision, AgentStep
from backend.services.agent_memory import record_fact, save_episode
from backend.services.agent_planner import decide
from backend.services.agent_tools import TOOL_REGISTRY

logger = get_logger("agent_runtime")

MAX_RESULT_CHARS = 6000


def _compact_result(result) -> dict:
    text = json.dumps(result, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        try:
            return json.loads(text[:MAX_RESULT_CHARS])
        except Exception:
            return {"truncated": text[: MAX_RESULT_CHARS // 2]}
    return result


def _facts_fingerprint(facts: dict) -> str:
    return json.dumps(facts, default=str, sort_keys=True, ensure_ascii=False)[:500]


class AgentRuntime:
    async def start(self, run_id: str) -> None:
        db = get_db()
        run = await db.agent_runs.find_one({"id": run_id})
        if not run:
            logger.warning("Agent run %s not found", run_id)
            return
        if run.get("status") in ("complete", "failed", "stopped"):
            return

        if run.get("status") == "waiting_approval":
            pending = run.get("pending_payload") or {}
            if pending.get("tool"):
                await self._execute_step(run, AgentDecision(
                    reasoning="Resumed after human approval.",
                    tool=pending["tool"],
                    args=pending.get("args") or {},
                ))
                run["updated_at"] = datetime.utcnow()
                await db.agent_runs.replace_one({"id": run_id}, run)

        await db.agent_runs.update_one(
            {"id": run_id},
            {"$set": {"status": "running", "pending_payload": None, "updated_at": datetime.utcnow()}},
        )
        run = await db.agent_runs.find_one({"id": run_id})
        if not run:
            return

        consecutive_failures = 0
        while True:
            fresh = await db.agent_runs.find_one({"id": run_id})
            if not fresh:
                return
            run = fresh
            if run.get("status") == "stopped":
                break
            if run.get("credits_spent", 0) >= run.get("budget_credits", 0):
                run["status"] = "failed"
                run["error"] = "budget exhausted"
                break
            if len(run.get("steps") or []) >= run.get("max_steps", 15):
                run["status"] = "failed"
                run["error"] = f"max_steps ({run.get('max_steps')}) reached"
                break

            decision = await self._decide_with_guard(run)
            if decision is None:
                run["status"] = "failed"
                run["error"] = "loop detected: repeated identical tool call with no state change"
                break
            if decision.tool == "complete":
                run["status"] = "complete"
                break

            spec = TOOL_REGISTRY.get(decision.tool)
            if not spec:
                run["status"] = "failed"
                run["error"] = f"unknown tool: {decision.tool}"
                break

            if spec.get("requires_checkpoint") and run.get("checkpoint_policy") != "never":
                run["status"] = "waiting_approval"
                run["pending_payload"] = {"tool": decision.tool, "args": decision.args}
                run["updated_at"] = datetime.utcnow()
                await db.agent_runs.replace_one({"id": run_id}, run)
                break

            await self._execute_step(run, decision)
            step = run["steps"][-1]
            if not step.get("ok"):
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    run["status"] = "failed"
                    run["error"] = f"tool {step.get('tool')} failed twice: {step.get('error')}"
                    break
            else:
                consecutive_failures = 0
            run["updated_at"] = datetime.utcnow()
            await db.agent_runs.replace_one({"id": run_id}, run)

        if run.get("status") != "waiting_approval":
            run["completed_at"] = datetime.utcnow()
            run["updated_at"] = datetime.utcnow()
            await db.agent_runs.replace_one({"id": run_id}, run)
            await self._persist_episode(run)

    async def approve(self, run_id: str) -> bool:
        db = get_db()
        run = await db.agent_runs.find_one({"id": run_id})
        if not run or run.get("status") != "waiting_approval":
            return False
        await self.start(run_id)
        return True

    async def stop(self, run_id: str) -> bool:
        db = get_db()
        run = await db.agent_runs.find_one({"id": run_id})
        if not run or run.get("status") not in ("queued", "running", "waiting_approval"):
            return False
        run["status"] = "stopped"
        run["completed_at"] = datetime.utcnow()
        run["updated_at"] = datetime.utcnow()
        await db.agent_runs.replace_one({"id": run_id}, run)
        await self._persist_episode(run)
        return True

    async def _decide_with_guard(self, run: dict) -> AgentDecision | None:
        steps = run.get("steps") or []
        state = self._build_state(run)
        decision = await decide(state)
        if not decision or not decision.tool:
            return None
        if decision.tool == "complete":
            return decision
        if len(steps) >= 1:
            prev = steps[-1]
            same_call = prev.get("tool") == decision.tool and json.dumps(prev.get("args"), sort_keys=True) == json.dumps(
                decision.args, sort_keys=True
            )
            if same_call:
                prev_fp = prev.get("facts_fp")
                facts_fp = _facts_fingerprint(run.get("facts") or {})
                if prev_fp == facts_fp:
                    return None
                if facts_fp in {s.get("facts_fp") for s in steps}:
                    return None
        return decision

    def _build_state(self, run: dict) -> dict:
        return {
            "goal": run.get("goal", ""),
            "domain": run.get("domain", ""),
            "scope": run.get("scope", "single_page"),
            "urls": run.get("urls") or [],
            "budget_remaining": max(0.0, float(run.get("budget_credits", 0)) - float(run.get("credits_spent", 0))),
            "steps_used": len(run.get("steps") or []),
            "max_steps": run.get("max_steps", 15),
            "facts": run.get("facts") or {},
        }

    async def _execute_step(self, run: dict, decision: AgentDecision) -> None:
        spec = TOOL_REGISTRY.get(decision.tool)
        step = AgentStep(
            step_num=len(run.get("steps") or []) + 1,
            tool=decision.tool,
            args=decision.args,
            reasoning=decision.reasoning,
        )
        start = time.perf_counter()
        if spec:
            spec_credit_cost = float(spec.get("credit_cost", 0))
            run["credits_spent"] = float(run.get("credits_spent", 0)) + spec_credit_cost
            try:
                handler = spec["handler"]
                result = await handler(**{**decision.args, "job_id": run.get("job_id")})
                step.result = _compact_result(result)
                step.ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
                if not step.ok and isinstance(result, dict) and result.get("error"):
                    step.error = str(result["error"])
            except Exception as e:
                step.ok = False
                step.error = str(e)
                step.result = None
        else:
            step.ok = False
            step.error = f"unknown tool: {decision.tool}"
        step.duration_ms = int((time.perf_counter() - start) * 1000)
        run.setdefault("steps", []).append(step.model_dump())
        self._extract_facts(run, step)
        run["steps"][-1]["facts_fp"] = _facts_fingerprint(run.get("facts") or {})
        await self._record_domain_facts(run, step)

    def _extract_facts(self, run: dict, step: AgentStep) -> None:
        facts = run.setdefault("facts", {})
        result = step.result or {}
        if step.tool == "crawl_urls":
            summary = result.get("summary") or {}
            if summary:
                facts["pages_crawled"] = summary.get("total_pages", 0)
            if result.get("page_facts"):
                facts["pages"] = result["page_facts"]
        elif step.tool == "run_analyzers":
            facts["analyze_done"] = True
        elif step.tool == "generate_suggestions":
            facts["suggestions_attempted"] = True
            created = result.get("created") or []
            facts["suggestions_pending"] = len(created)
            ids = [c["id"] for c in created]
            facts["suggestion_ids_pending"] = ids
        elif step.tool == "apply_to_sandbox":
            facts["apply_attempted"] = True
            applied = result.get("applied") or []
            pending_ids = list(facts.get("suggestion_ids_pending") or [])
            applied_ids = {a["id"] for a in applied}
            facts["suggestion_ids_pending"] = [i for i in pending_ids if i not in applied_ids]
            facts["suggestions_pending"] = len(facts["suggestion_ids_pending"])
            facts["suggestions_applied"] = facts.get("suggestions_applied", 0) + len(applied)
            ids = result.get("staging_page_ids") or []
            if ids:
                facts["staging_page_ids"] = list(dict.fromkeys(list(facts.get("staging_page_ids") or []) + ids))
        elif step.tool == "verify_changes":
            facts["verification_done"] = True
            comparison = result.get("comparison") or {}
            score = comparison.get("seo_score") or {}
            if score.get("delta") is not None:
                facts["seo_score_delta"] = score["delta"]
                facts["seo_score_before"] = score.get("old")
                facts["seo_score_after"] = score.get("new")

    async def _record_domain_facts(self, run: dict, step: AgentStep) -> None:
        domain = run.get("domain", "")
        if not domain:
            return
        result = step.result or {}
        if step.tool == "crawl_urls" and result.get("page_facts"):
            for p in result["page_facts"]:
                key = "page_title_length"
                await record_fact(domain, f"{key}:{p.get('url', '')[:80]}", p.get("title_length", 0), source_run=run.get("id"))
        elif step.tool == "generate_suggestions":
            await record_fact(
                domain,
                "last_suggestion_count",
                result.get("count", 0),
                source_run=run.get("id"),
            )
        elif step.tool == "verify_changes":
            await record_fact(
                domain,
                "last_seo_score_delta",
                (result.get("comparison") or {}).get("seo_score", {}).get("delta"),
                source_run=run.get("id"),
            )

    async def _persist_episode(self, run: dict) -> None:
        try:
            await save_episode(run)
        except Exception as e:
            logger.warning("Episode save failed for %s: %s", run.get("id"), e)
