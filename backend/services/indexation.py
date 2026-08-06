"""Indexation audit: `site:` SERP check against Google's live index.

Uses the spend-tracked SERP API; degrades to "unmeasured" (status) when no
SERP key is configured — matching the external-service resilience behavior.
The estimate is Google's own "results" count, so it is clearly labeled as an
estimate, never a promise.
"""

from datetime import datetime
from urllib.parse import urlparse

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.service_errors import ServiceError
from backend.services.serp_api import search_keyword

logger = get_logger("indexation")


async def check_indexation(job_id: str, target_url: str) -> dict:
    db = get_db()
    domain = urlparse(target_url).netloc.lower() or target_url.split("//")[-1].split("/")[0]
    crawled = await db.pages.count_documents({"job_id": job_id})

    try:
        result = await search_keyword(f"site:{domain}")
    except ServiceError as e:
        summary = {
            "job_id": job_id,
            "domain": domain,
            "status": "unmeasured",
            "crawled_pages": crawled,
            "message": f"Indexation check not run: {e.hint or str(e)}",
            "generated_at": datetime.utcnow(),
        }
        await db.indexation_audits.update_one(
            {"job_id": job_id},
            {"$set": summary},
            upsert=True,
        )
        logger.info("Indexation unmeasured job=%s domain=%s: %s", job_id, domain, e)
        return summary

    indexed_estimate = result.get("total_results") or result.get("organic_count") or 0
    top_pages = [r for r in result.get("top_results") or [] if domain in (r.get("url") or "")][:8]

    summary = {
        "job_id": job_id,
        "domain": domain,
        "status": "measured",
        "indexed_estimate": indexed_estimate,
        "crawled_pages": crawled,
        "organic_count": result.get("organic_count", 0),
        "top_indexed_pages": top_pages,
        "note": "total_results is Google's own estimate for the site: query",
        "generated_at": datetime.utcnow(),
    }
    await db.indexation_audits.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("Indexation job=%s domain=%s estimate=%s crawled=%s",
                job_id, domain, indexed_estimate, crawled)
    return summary
