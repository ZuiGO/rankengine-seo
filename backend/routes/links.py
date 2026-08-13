from fastapi import APIRouter, Query

from backend.db.mongo import get_db
from backend.services.backlinks import get_backlinks
from backend.services.link_checker import check_links, get_link_health
from backend.services.url_normalizer import normalize_url

router = APIRouter(prefix="/api/links", tags=["links"])


@router.get("/{job_id}")
async def get_link_summary(job_id: str):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}

    summary = job.get("summary") or {}
    occurrences = summary.get("total_link_occurrences") or summary.get("total_links", 0)
    return {
        "total_links": summary.get("total_links", 0),
        "total_internal": summary.get("total_internal_links", 0),
        "total_external": summary.get("total_external_links", 0),
        "total_link_occurrences": occurrences,
    }


@router.get("/{job_id}/all")
async def all_links(job_id: str, status: str | None = None, external: bool | None = None, limit: int = Query(200, le=1000), offset: int = Query(0)):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id}, {"_id": 1})
    if not job:
        return {"error": "Job not found"}
    q: dict = {"job_id": job_id}
    if status:
        q["status"] = status
    if external is not None:
        q["external"] = external
    flagged = await db.link_health.count_documents({"job_id": job_id, "external": {"$exists": True}})
    fallback = flagged == 0
    if fallback and external is not None:
        q.pop("external", None)
    total = await db.link_health.count_documents(q)
    unchecked_count = await db.link_health.count_documents({"job_id": job_id, "status": "unchecked"})
    cursor = db.link_health.find(q).sort("url", 1).skip(offset).limit(limit)
    rows = []
    async for r in cursor:
        r["id"] = str(r.pop("_id"))
        rows.append(r)

    if fallback:
        external_urls = set()
        page_cursor = db.page_links.find({"job_id": job_id}, {"external_link_urls": 1})
        async for doc in page_cursor:
            for target in doc.get("external_link_urls", []) or []:
                norm = normalize_url(target)
                if norm:
                    external_urls.add(norm)
        for r in rows:
            r["external"] = r.get("url") in external_urls
        if external is not None:
            rows = [r for r in rows if r["external"] is external]
            total = len(rows)
    return {"total": total, "links": rows, "offset": offset, "limit": limit, "unchecked_count": unchecked_count}


@router.get("/{job_id}/backlinks")
async def list_backlinks(job_id: str):
    return await get_backlinks(job_id, limit=1000)


@router.get("/{job_id}/health")
async def link_health(job_id: str, limit: int = Query(100, le=500), offset: int = Query(0)):
    return await get_link_health(job_id, limit, offset)


@router.post("/{job_id}/check")
async def run_link_check(job_id: str):
    summary = await check_links(job_id)
    return summary


@router.get("/{job_id}/graph")
async def get_crawl_graph(job_id: str, limit: int = Query(100, ge=0, le=1000)):
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id}, {"_id": 1})
    if not job:
        return {"error": "Job not found"}

    page_cursor = db.pages.find(
        {"job_id": job_id},
        {"url": 1, "title": 1, "status_code": 1, "word_count": 1, "page_type": 1, "h1_count": 1}
    )
    pages_list = []
    async for p in page_cursor:
        pages_list.append(p)
    pages_by_url = {p["url"]: p for p in pages_list}

    lh_cursor = db.link_health.find({"job_id": job_id}, {"url": 1, "status": 1, "status_code": 1, "external": 1})
    link_health_map = {}
    async for lh in lh_cursor:
        link_health_map[lh["url"]] = lh

    pl_cursor = db.page_links.find({"job_id": job_id}, {"url": 1, "internal_link_urls": 1, "external_link_urls": 1})
    page_links_list = []
    async for pl in pl_cursor:
        page_links_list.append(pl)

    nodes_map = {}
    edges_list = []
    edges_set = set()

    def ensure_node(url: str, is_page: bool = False):
        if url not in nodes_map:
            p_data = pages_by_url.get(url) or {}
            lh_data = link_health_map.get(url) or {}

            status_code = p_data.get("status_code") or lh_data.get("status_code") or 200
            ext = lh_data.get("external", False) if "external" in lh_data else not is_page

            if lh_data.get("status"):
                status = lh_data["status"]
            elif status_code == 200:
                status = "ok"
            elif status_code in (301, 302):
                status = "redirect"
            elif status_code in (404, 500):
                status = "broken"
            elif status_code == 403:
                status = "blocked"
            elif status_code == 0 or status_code is None:
                status = "unreachable"
            else:
                status = "unchecked"

            if ext and status == "ok":
                status = "external"

            nodes_map[url] = {
                "id": url,
                "title": p_data.get("title") or url.split("/")[-1] or url,
                "status": status,
                "status_code": status_code,
                "external": ext,
                "word_count": p_data.get("word_count", 0),
                "page_type": p_data.get("page_type", "other"),
                "in_degree": 0,
                "out_degree": 0,
                "issues": 1 if status in ("broken", "unreachable", "blocked") else 0,
            }

    for p in pages_list:
        ensure_node(p["url"], is_page=True)

    for pl in page_links_list:
        src = pl.get("url")
        if not src:
            continue
        ensure_node(src, is_page=True)

        internals = pl.get("internal_link_urls") or []
        externals = pl.get("external_link_urls") or []

        for tgt in internals:
            if not tgt or src == tgt:
                continue
            ensure_node(tgt, is_page=True)
            edge_key = (src, tgt)
            if edge_key not in edges_set:
                edges_set.add(edge_key)
                nodes_map[src]["out_degree"] += 1
                nodes_map[tgt]["in_degree"] += 1
                lh = link_health_map.get(tgt) or {}
                edges_list.append({
                    "source": src,
                    "target": tgt,
                    "status": lh.get("status", "ok"),
                    "status_code": lh.get("status_code", 200),
                    "external": False
                })

        for tgt in externals:
            if not tgt or src == tgt:
                continue
            ensure_node(tgt, is_page=False)
            edge_key = (src, tgt)
            if edge_key not in edges_set:
                edges_set.add(edge_key)
                nodes_map[src]["out_degree"] += 1
                nodes_map[tgt]["in_degree"] += 1
                lh = link_health_map.get(tgt) or {}
                edges_list.append({
                    "source": src,
                    "target": tgt,
                    "status": lh.get("status", "external"),
                    "status_code": lh.get("status_code", 200),
                    "external": True
                })

    all_nodes = list(nodes_map.values())
    total_nodes = len(all_nodes)
    total_edges = len(edges_list)
    broken_count = sum(1 for n in all_nodes if n["status"] in ("broken", "unreachable"))

    if limit > 0 and len(all_nodes) > limit:
        all_nodes.sort(key=lambda n: (n["status"] in ("broken", "unreachable", "blocked"), n["in_degree"] + n["out_degree"]), reverse=True)
        selected_ids = {n["id"] for n in all_nodes[:limit]}
        all_nodes = [n for n in all_nodes if n["id"] in selected_ids]
        edges_list = [e for e in edges_list if e["source"] in selected_ids and e["target"] in selected_ids]

    return {
        "nodes": all_nodes,
        "edges": edges_list,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "broken_nodes_count": broken_count,
        "is_limited": limit > 0 and total_nodes > limit
    }
