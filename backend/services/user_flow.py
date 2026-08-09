import uuid
from datetime import datetime

from backend.db.mongo import get_db
from backend.db.neo4j_db import get_driver
from backend.logging_setup import get_logger

logger = get_logger("user_flow")


async def detect_user_flows(job_id: str) -> int:
    """Infer user flows (entry -> browse -> action) from the internal link graph."""
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}).to_list(length=None)
    if not pages:
        return 0

    page_types = {p["url"]: p.get("page_type", "other") for p in pages}
    page_roles = {p["url"]: p.get("page_role", "browse") for p in pages}

    links_to = {}
    link_cursor = db.page_links.find({"job_id": job_id})
    async for link_doc in link_cursor:
        source = link_doc["url"]
        if source not in page_types:
            continue
        for target in link_doc.get("internal_link_urls", []):
            if target in page_types:
                links_to.setdefault(source, set()).add(target)

    linked_from = {}
    for source, targets in links_to.items():
        for target in targets:
            linked_from.setdefault(target, set()).add(source)

    def role_of(url: str) -> str:
        return page_roles.get(url, "browse")

    flows = []
    seen_flows = set()

    for action_url in page_types:
        if role_of(action_url) != "action":
            continue

        for b_url in sorted(linked_from.get(action_url, [])):
            if b_url == action_url:
                continue
            if role_of(b_url) in ("entry", "browse"):
                direct = (b_url, action_url)
                if direct not in seen_flows:
                    seen_flows.add(direct)
                    flows.append({
                        "start_url": b_url,
                        "start_type": page_types.get(b_url, "other"),
                        "intermediate_url": None,
                        "intermediate_type": None,
                        "target_url": action_url,
                        "target_type": page_types.get(action_url, "other"),
                        "steps": [b_url, action_url],
                        "depth": 1,
                    })

            for e_url in sorted(linked_from.get(b_url, [])):
                if e_url in (action_url, b_url):
                    continue
                if role_of(e_url) != "entry":
                    continue
                triple = (e_url, b_url, action_url)
                if triple in seen_flows:
                    continue
                seen_flows.add(triple)
                flows.append({
                    "start_url": e_url,
                    "start_type": page_types.get(e_url, "other"),
                    "intermediate_url": b_url,
                    "intermediate_type": page_types.get(b_url, "other"),
                    "target_url": action_url,
                    "target_type": page_types.get(action_url, "other"),
                    "steps": [e_url, b_url, action_url],
                    "depth": 2,
                })

    if not flows:
        return 0

    now = datetime.utcnow()
    for flow in flows:
        flow["job_id"] = job_id
        flow["flow_id"] = str(uuid.uuid4())
        flow["created_at"] = now

    await db.user_flows.delete_many({"job_id": job_id})
    await db.user_flows.insert_many(flows)

    try:
        await _store_flows_in_graph(job_id, flows)
    except Exception as e:
        logger.warning("User flow graph write warning job=%s: %s", job_id, e)

    logger.info("User flows detected job=%s flows=%s", job_id, len(flows))
    return len(flows)


async def _store_flows_in_graph(job_id: str, flows: list):
    driver = get_driver()
    if not driver:
        return

    async with driver.session(database="neo4j") as session:
        await session.run(
            "MATCH (f:UserFlow {job_id: $job_id}) DETACH DELETE f", job_id=job_id
        )
        for flow in flows:
            steps = flow["steps"]
            await session.run(
                """
                MERGE (f:UserFlow {flow_id: $flow_id, job_id: $job_id})
                SET f.start_url = $start_url,
                    f.start_type = $start_type,
                    f.target_url = $target_url,
                    f.target_type = $target_type,
                    f.depth = $depth
                WITH f
                MATCH (a:Page {url: $start_url, job_id: $job_id})
                MERGE (f)-[:STARTS_AT]->(a)
                WITH f
                MATCH (c:Page {url: $target_url, job_id: $job_id})
                MERGE (f)-[:ENDS_AT]->(c)
                """,
                flow_id=flow["flow_id"],
                job_id=job_id,
                start_url=flow["start_url"],
                start_type=flow["start_type"],
                target_url=flow["target_url"],
                target_type=flow["target_type"],
                depth=flow["depth"],
            )
            if flow.get("intermediate_url"):
                await session.run(
                    """
                    MATCH (f:UserFlow {flow_id: $flow_id, job_id: $job_id})
                    MATCH (b:Page {url: $via_url, job_id: $job_id})
                    MERGE (f)-[:STEPS_THROUGH]->(b)
                    """,
                    flow_id=flow["flow_id"],
                    job_id=job_id,
                    via_url=flow["intermediate_url"],
                )


async def get_user_flows(job_id: str, limit: int = 100) -> dict:
    db = get_db()
    flows = await db.user_flows.find({"job_id": job_id}).to_list(length=limit)
    for f in flows:
        f["id"] = str(f.pop("_id"))
    total = await db.user_flows.count_documents({"job_id": job_id})
    return {"flows": flows, "total": total}


async def get_top_flows(job_id: str, limit: int = 10) -> list:
    """Top action targets by funnel size: distinct pages that link into the target
    (unique intermediate browse pages for 2-hop flows, unique entry pages for
    1-hop flows). Avoids the combinatorial entry x browse path inflation."""
    db = get_db()
    pipeline = [
        {"$match": {"job_id": job_id}},
        {"$group": {
            "_id": {"target": "$target_url", "target_type": "$target_type", "depth": "$depth"},
            "funnel": {"$addToSet": {
                "$cond": [
                    {"$eq": ["$depth", 2]},
                    {"$ifNull": ["$intermediate_url", "$start_url"]},
                    "$start_url",
                ]
            }},
        }},
        {"$project": {
            "flow_count": {"$size": "$funnel"},
        }},
        {"$sort": {"flow_count": -1}},
        {"$limit": limit},
    ]
    rows = []
    cursor = db.user_flows.aggregate(pipeline)
    async for row in cursor:
        rows.append({
            "target_url": row["_id"]["target"],
            "target_type": row["_id"]["target_type"],
            "depth": row["_id"]["depth"],
            "flow_count": row["flow_count"],
        })
    return rows
