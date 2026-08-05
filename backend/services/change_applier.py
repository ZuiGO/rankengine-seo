import asyncio
import difflib
import json
import time
from datetime import datetime

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("change_applier")

LAST_GROQ_429 = 0.0
QA_SEM = asyncio.Semaphore(2)

FIELD_BY_TYPE = {
    "image": "alt_text",
    "text": "meta_description",
    "pdf": "link_text",
    "doc": "link_text",
    "xlsx": "link_text",
    "presentation": "link_text",
    "video": "link_text",
    "audio": "link_text",
}

FALLBACK_AFTER = {
    "alt_text": "Image: {filename}",
    "meta_description": "{page_title} - learn more in this detailed guide",
    "link_text": "Download {filename}",
    "title": "{page_title}",
}

PROMPT_BY_FIELD = {
    "alt_text": (
        "Write an SEO-optimized alt text (max 125 characters) for the image below. "
        "Describe what the image shows and include relevant keywords naturally."
    ),
    "meta_description": (
        "Write an SEO-optimized meta description (140-160 characters) for the page below. "
        "Summarize the page value and include a call to action."
    ),
    "link_text": (
        "Write descriptive, SEO-friendly anchor text (max 60 characters) for the link to "
        "this document/resource. Avoid generic text like 'click here' or 'download'."
    ),
    "title": (
        "Write an SEO-optimized HTML title tag (50-60 characters) for the page below. "
        "Put the primary keyword near the beginning."
    ),
}

GROQ_MODEL = settings.groq_model


async def _build_context(item: dict) -> str:
    db = get_db()
    page = await db.pages.find_one({"job_id": item.get("job_id"), "url": item.get("page_url")})
    title = (page or {}).get("title", "")
    meta = (page or {}).get("meta_description", "")
    filename = (item.get("source_url", "") or "").split("/")[-1]
    return (
        f"Content type: {item.get('content_type', '')}\n"
        f"Page URL: {item.get('page_url', '')}\n"
        f"Page title: {title}\n"
        f"Page meta description: {meta}\n"
        f"Resource URL: {item.get('source_url', '')}\n"
        f"Resource filename: {filename}"
    )


async def _groq_generate(item: dict, field: str) -> str | None:
    if not settings.groq_api_key:
        return None
    try:
        from groq import AsyncGroq

        from backend.services.groq_limiter import acquire_token_budget

        await acquire_token_budget()
        client = AsyncGroq(api_key=settings.groq_api_key)
        context = await _build_context(item)
        prompt = PROMPT_BY_FIELD.get(
            field,
            "Improve the SEO quality of this content element based on the context.",
        )
        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate SEO content fixes. Respond with STRICT JSON only: "
                        '{"field": "<field name>", "after": "<improved text>"}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"Field to improve: {field}\n\nContext:\n{context}\n\nTask:\n{prompt}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=300,
        )
        content = completion.choices[0].message.content
        parsed = json.loads(content)
        after = str(parsed.get("after") or parsed.get(field) or "").strip()
        try:
            from backend.services.spend_tracker import record_usage
            usage = getattr(completion, "usage", None)
            await record_usage("groq", item.get("job_id", ""), "change_generation",
                               tokens=(usage.total_tokens if usage else 0))
        except Exception:
            pass
        return after or None
    except Exception as e:
        if "429" in str(e):
            global LAST_GROQ_429
            LAST_GROQ_429 = time.time()
        logger.warning("Groq change generation failed action=%s: %s", item.get("_id"), e)
        return None


async def _before_value(item: dict, field: str) -> str:
    if field == "alt_text":
        filename = (item.get("source_url", "") or "").split("/")[-1]
        return filename or (item.get("source_url", "") or "")
    if field == "link_text":
        return (item.get("source_url", "") or "").split("/")[-1]
    if field == "meta_description":
        db = get_db()
        page = await db.pages.find_one({"job_id": item.get("job_id"), "url": item.get("page_url")})
        return (page or {}).get("meta_description", "") or (item.get("page_url", ""))
    return item.get("page_url", "")


def _fallback_after(item: dict, field: str) -> str:
    filename = (item.get("source_url", "") or "").split("/")[-1]
    page_title = ""
    template = FALLBACK_AFTER.get(field, "{page_title}")
    return template.format(page_title=page_title, filename=filename)


def _make_diff(before: str, after: str) -> list[str]:
    diff = list(difflib.ndiff(before.splitlines(), after.splitlines()))
    return [line for line in diff if line[:1] in ("+", "-")][:40]


async def _qa_check(item: dict, before: str, after: str) -> bool:
    """Factual-consistency check of the rewrite vs the original. Failures degrade to 'proceed'."""
    global LAST_GROQ_429
    if not settings.groq_api_key or not before or not after:
        return True
    if time.time() - LAST_GROQ_429 < 60:
        return True
    async with QA_SEM:
        try:
            from groq import AsyncGroq

            from backend.services.groq_limiter import acquire_token_budget

            await acquire_token_budget(est_tokens=300)
            client = AsyncGroq(api_key=settings.groq_api_key)
            completion = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You verify that an SEO rewrite is factually consistent with its original. "
                            'Respond with STRICT JSON only: {"consistent": true or false, "note": "short reason if inconsistent, else empty string"}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Original:\n{before}\n\nRewritten:\n{after}\n\n"
                            "Check that numbers, names, prices, URLs, dates and factual claims still match. "
                            "Is the rewrite factually consistent with the original?"
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=200,
            )
            content = completion.choices[0].message.content
            parsed = json.loads(content)
            try:
                from backend.services.spend_tracker import record_usage
                usage = getattr(completion, "usage", None)
                await record_usage("groq", item.get("job_id", ""), "qa_check",
                                   tokens=(usage.total_tokens if usage else 0))
            except Exception:
                pass
            return bool(parsed.get("consistent", True))
        except Exception as e:
            if "429" in str(e):
                LAST_GROQ_429 = time.time()
            logger.warning("QA check failed action=%s: %s", item.get("_id"), e)
            return True


async def create_version_for_action(item: dict, status: str) -> dict | None:
    """Generate the improved content for an approved action and store a before/after version."""
    db = get_db()
    ctype = item.get("content_type", "text")
    field = FIELD_BY_TYPE.get(ctype, "text")

    before = await _before_value(item, field)

    qa_status = "skipped"
    if status == "approved":
        after = await _groq_generate(item, field)
        if after:
            if await _qa_check(item, before, after):
                qa_status = "passed"
            else:
                after = _fallback_after(item, field)
                qa_status = "fallback"
        else:
            after = _fallback_after(item, field)
            qa_status = "template"
        generated_by = "groq:" + GROQ_MODEL if settings.groq_api_key else "fallback"
    else:
        after = None
        generated_by = None

    version = {
        "job_id": item.get("job_id"),
        "action_id": str(item.get("_id")),
        "issue_key": item.get("issue_key", ""),
        "page_url": item.get("page_url", ""),
        "content_item_id": item.get("content_item_id", ""),
        "content_type": ctype,
        "source_url": item.get("source_url", ""),
        "field": field,
        "before": before,
        "after": after,
        "diff": _make_diff(before, after) if after else [],
        "status": status,
        "generated_by": generated_by,
        "qa": qa_status,
        "reviewed_at": datetime.utcnow(),
    }
    await db.content_versions.insert_one(version)
    return {k: v for k, v in version.items() if k != "_id"}


async def get_content_versions(job_id: str, limit: int = 500) -> dict:
    db = get_db()
    cursor = (
        db.content_versions.find({"job_id": job_id})
        .sort("reviewed_at", -1)
        .limit(limit)
    )
    versions = await cursor.to_list(length=limit)
    for v in versions:
        v["id"] = str(v.pop("_id"))
    total = await db.content_versions.count_documents({"job_id": job_id})
    applied = await db.content_versions.count_documents({"job_id": job_id, "status": "approved"})
    return {"versions": versions, "total": total, "applied": applied}
