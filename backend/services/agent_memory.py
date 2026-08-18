"""Durable agent memory: episodes + cross-run domain facts."""

from datetime import datetime
from typing import Any

from backend.db.mongo import get_db


async def save_episode(run: dict) -> None:
    db = get_db()
    episode = {
        "run_id": run.get("id"),
        "goal": run.get("goal"),
        "domain": run.get("domain", ""),
        "scope": run.get("scope"),
        "steps": run.get("steps", []),
        "facts": run.get("facts", {}),
        "outcome": run.get("status"),
        "error": run.get("error"),
        "credits_spent": run.get("credits_spent", 0),
        "started_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
    }
    await db.agent_episodes.update_one(
        {"run_id": run.get("id")},
        {"$set": episode},
        upsert=True,
    )


async def get_episode(run_id: str) -> dict | None:
    db = get_db()
    doc = await db.agent_episodes.find_one({"run_id": run_id})
    if doc and "_id" in doc:
        del doc["_id"]
    return doc


async def record_fact(domain: str, key: str, value: Any, confidence: float = 1.0, source_run: str | None = None) -> None:
    if not domain:
        return
    db = get_db()
    await db.agent_facts.update_one(
        {"domain": domain, "fact_key": key},
        {
            "$set": {
                "value": value,
                "confidence": confidence,
                "source_run": source_run,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


async def get_facts(domain: str) -> dict[str, Any]:
    if not domain:
        return {}
    db = get_db()
    cursor = db.agent_facts.find({"domain": domain})
    facts = {}
    async for doc in cursor:
        facts[doc.get("fact_key")] = doc.get("value")
    return facts


async def recent_episodes(domain: str, limit: int = 5) -> list[dict]:
    if not domain:
        return []
    db = get_db()
    cursor = db.agent_episodes.find({"domain": domain}).sort("started_at", -1).limit(limit)
    episodes = await cursor.to_list(length=limit)
    for e in episodes:
        if "_id" in e:
            del e["_id"]
        e["steps"] = []
    return episodes
