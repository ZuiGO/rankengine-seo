from neo4j import AsyncSession
from backend.db.neo4j_db import get_driver
from backend.db.mongo import get_db


BATCH_SIZE = 100


async def populate_graph(job_id: str):
    driver = get_driver()
    if not driver:
        return False

    db = get_db()

    page_cursor = db.pages.find({"job_id": job_id})
    pages = await page_cursor.to_list(length=None)

    content_cursor = db.content_items.find({"job_id": job_id})
    content_items = await content_cursor.to_list(length=None)

    async with driver.session(database="neo4j") as session:
        await session.run("MATCH (n) WHERE n.job_id = $job_id DETACH DELETE n", job_id=job_id)

        # Batch insert pages
        for i in range(0, len(pages), BATCH_SIZE):
            batch = pages[i:i + BATCH_SIZE]
            await session.run(
                """
                UNWIND $pages AS p
                MERGE (page:Page {url: p.url, job_id: p.job_id})
                SET page.title = p.title,
                    page.word_count = p.word_count,
                    page.status_code = p.status_code,
                    page.h1_count = p.h1_count,
                    page.internal_links = p.internal_links,
                    page.external_links = p.external_links,
                    page.has_structured_data = p.has_structured_data,
                    page.is_indexable = p.is_indexable,
                    page.page_type = p.page_type,
                    page.page_role = p.page_role,
                    page.content_types = p.content_types
                """,
                pages=[
                    {
                        "url": p["url"],
                        "job_id": job_id,
                        "title": p.get("title", ""),
                        "word_count": p.get("word_count", 0),
                        "status_code": p.get("status_code", 200),
                        "h1_count": p.get("h1_count", 0),
                        "internal_links": p.get("internal_links", 0),
                        "external_links": p.get("external_links", 0),
                        "has_structured_data": p.get("has_structured_data", False),
                        "is_indexable": p.get("is_indexable", True),
                        "page_type": p.get("page_type", "other"),
                        "page_role": p.get("page_role", "browse"),
                        "content_types": p.get("content_types", []),
                    }
                    for p in batch
                ],
            )

        # Batch insert content items
        for i in range(0, len(content_items), BATCH_SIZE):
            batch = content_items[i:i + BATCH_SIZE]
            await session.run(
                """
                UNWIND $items AS item
                MERGE (c:ContentItem {source_url: item.source_url, job_id: item.job_id})
                SET c.content_type = item.content_type,
                    c.file_size = item.file_size,
                    c.mime_type = item.mime_type,
                    c.page_url = item.page_url
                WITH c, item
                MATCH (p:Page {url: item.page_url, job_id: item.job_id})
                MERGE (p)-[:HAS_CONTENT]->(c)
                """,
                items=[
                    {
                        "source_url": c["source_url"],
                        "job_id": job_id,
                        "content_type": c.get("content_type", ""),
                        "file_size": c.get("file_size"),
                        "mime_type": c.get("mime_type", ""),
                        "page_url": c.get("page_url", ""),
                    }
                    for c in batch
                ],
            )

        # Collect and batch internal links (deduplicated)
        link_pairs = set()
        page_urls = {p["url"] for p in pages}
        link_cursor = db.page_links.find({"job_id": job_id})
        async for link_doc in link_cursor:
            for target_url in link_doc.get("internal_link_urls", []):
                if target_url in page_urls:
                    link_pairs.add((link_doc["url"], target_url))

        link_list = [{"source": s, "target": t, "job_id": job_id} for s, t in link_pairs]
        for i in range(0, len(link_list), BATCH_SIZE):
            batch = link_list[i:i + BATCH_SIZE]
            await session.run(
                """
                UNWIND $links AS l
                MATCH (a:Page {url: l.source, job_id: l.job_id})
                MATCH (b:Page {url: l.target, job_id: l.job_id})
                MERGE (a)-[:LINKS_TO]->(b)
                """,
                links=batch,
            )

        # Store summary
        await session.run(
            """
            MERGE (s:SiteSummary {job_id: $job_id})
            SET s.url = $url,
                s.page_count = $page_count,
                s.content_count = $content_count,
                s.internal_link_count = $internal_link_count
            """,
            job_id=job_id,
            url=pages[0]["url"] if pages else "",
            page_count=len(pages),
            content_count=len(content_items),
            internal_link_count=len(link_list),
        )

    return True


async def get_graph_data(job_id: str) -> dict:
    driver = get_driver()
    if not driver:
        return {"nodes": [], "edges": []}

    nodes = []
    edges = []
    seen_ids = set()

    async with driver.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (p:Page {job_id: $job_id}) RETURN p.url AS id, p.url AS label, 'page' AS type, p.title AS title",
            job_id=job_id,
        )
        async for record in result:
            nid = record["id"]
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append({
                    "id": nid, "label": record["label"],
                    "type": record["type"], "title": record.get("title", ""),
                })

        result = await session.run(
            """
            MATCH (c:ContentItem {job_id: $job_id})
            RETURN c.source_url AS id, c.content_type AS label, 'content' AS type
            """,
            job_id=job_id,
        )
        async for record in result:
            nid = record["id"]
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append({
                    "id": nid, "label": record["label"],
                    "type": record["type"],
                })

        result = await session.run(
            """
            MATCH (p:Page {job_id: $job_id})-[r:HAS_CONTENT]->(c:ContentItem)
            RETURN p.url AS source, c.source_url AS target, 'HAS_CONTENT' AS type
            """,
            job_id=job_id,
        )
        async for record in result:
            edges.append({
                "source": record["source"],
                "target": record["target"],
                "type": record["type"],
            })

        result = await session.run(
            """
            MATCH (a:Page {job_id: $job_id})-[r:LINKS_TO]->(b:Page {job_id: $job_id})
            RETURN a.url AS source, b.url AS target, 'LINKS_TO' AS type
            """,
            job_id=job_id,
        )
        async for record in result:
            edges.append({
                "source": record["source"],
                "target": record["target"],
                "type": record["type"],
            })

        result = await session.run(
            """
            MATCH (f:UserFlow {job_id: $job_id})
            RETURN f.flow_id AS id, f.start_type AS start_type, f.target_url AS target_url, f.depth AS depth
            """,
            job_id=job_id,
        )
        async for record in result:
            fid = record["id"]
            if fid not in seen_ids:
                seen_ids.add(fid)
                nodes.append({
                    "id": fid,
                    "label": f"flow -> {record.get('target_url', '')}",
                    "type": "flow",
                    "subtype": record.get("depth", 0),
                })

        result = await session.run(
            """
            MATCH (f:UserFlow {job_id: $job_id})-[r:STARTS_AT|STEPS_THROUGH|ENDS_AT]->(p:Page)
            RETURN f.flow_id AS source, p.url AS target, type(r) AS type
            """,
            job_id=job_id,
        )
        async for record in result:
            edges.append({
                "source": record["source"],
                "target": record["target"],
                "type": record["type"],
            })

    return {"nodes": nodes, "edges": edges}


async def get_graph_summary(job_id: str) -> dict:
    driver = get_driver()
    if not driver:
        return {}

    async with driver.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (s:SiteSummary {job_id: $job_id}) RETURN s",
            job_id=job_id,
        )
        record = await result.single()
        if record:
            props = dict(record["s"])
            return {k: v for k, v in props.items() if k != "job_id"}
    return {}
