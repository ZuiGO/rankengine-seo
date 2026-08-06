"""API spend / usage tracking.

Every external API call records a usage line in `api_usage`. Free-tier services are
tracked by request/token counts; estimated costs use configurable per-1M-token rates
(0 on free tiers) so budgets stay visible when paid tiers are used.
"""

from datetime import datetime

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.config import settings

logger = get_logger("spend")

SERVICE_RATES = {
    "gemini": {"rate_per_1m_tokens": settings.gemini_cost_per_million, "unit": "tokens"},
    "groq": {"rate_per_1m_tokens": settings.groq_cost_per_million, "unit": "tokens"},
    "pagespeed": {"rate_per_1m_tokens": 0, "unit": "requests"},
    "serp": {"rate_per_1m_tokens": 0, "unit": "requests"},
    "se_ranking": {"rate_per_1m_tokens": 0, "unit": "requests"},
    "dataforseo": {"rate_per_1m_tokens": settings.dataforseo_cost_per_million, "unit": "requests"},
}


async def record_usage(
    service: str,
    job_id: str,
    endpoint: str,
    tokens: int = 0,
    requests: int = 1,
    est_cost: float | None = None,
):
    try:
        db = get_db()
        if est_cost is None:
            rate = SERVICE_RATES.get(service, {}).get("rate_per_1m_tokens", 0)
            est_cost = round(tokens / 1_000_000 * rate, 6) if rate else 0.0
        await db.api_usage.insert_one({
            "service": service,
            "job_id": job_id,
            "endpoint": endpoint,
            "tokens": tokens,
            "requests": requests,
            "est_cost": est_cost,
            "recorded_at": datetime.utcnow(),
        })
    except Exception as e:
        logger.debug("usage record failed service=%s: %s", service, e)


async def get_spend_summary(job_id: str) -> dict:
    db = get_db()
    pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {
            "_id": "$service",
            "requests": {"$sum": "$requests"},
            "tokens": {"$sum": "$tokens"},
            "est_cost": {"$sum": "$est_cost"},
        }},
        {"$sort": {"est_cost": -1}},
    ]
    rows = []
    total_cost = 0.0
    total_requests = 0
    async for row in db.api_usage.aggregate(pipeline):
        rows.append({"service": row["_id"], **{k: row[k] for k in ("requests", "tokens", "est_cost")}})
        total_cost += row["est_cost"]
        total_requests += row["requests"]
    return {
        "job_id": job_id,
        "services": rows,
        "total_requests": total_requests,
        "total_est_cost": round(total_cost, 6),
    }


async def get_global_spend() -> dict:
    db = get_db()
    pipeline = [
        {"$group": {
            "_id": "$service",
            "requests": {"$sum": "$requests"},
            "tokens": {"$sum": "$tokens"},
            "est_cost": {"$sum": "$est_cost"},
        }},
        {"$sort": {"est_cost": -1}},
    ]
    rows = []
    total_cost = 0.0
    total_requests = 0
    async for row in db.api_usage.aggregate(pipeline):
        rows.append({"service": row["_id"], **{k: row[k] for k in ("requests", "tokens", "est_cost")}})
        total_cost += row["est_cost"]
        total_requests += row["requests"]
    return {"services": rows, "total_requests": total_requests, "total_est_cost": round(total_cost, 6)}
