from motor.motor_asyncio import AsyncIOMotorClient

client: AsyncIOMotorClient | None = None


async def connect_db(uri: str):
    global client
    client = AsyncIOMotorClient(uri)
    return client.rankengine


async def ensure_indexes():
    db = client.rankengine
    coll = db.content_items
    dups = await coll.aggregate([
        {"$group": {"_id": {"job_id": "$job_id", "content_type": "$content_type", "source_url": "$source_url"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 1},
    ]).to_list(length=1)
    if dups:
        await coll.create_index(
            [("job_id", 1), ("content_type", 1), ("source_url", 1)], name="content_item"
        )
    else:
        await coll.create_index(
            [("job_id", 1), ("content_type", 1), ("source_url", 1)], unique=True, name="content_item_uniq"
        )
    await db.agent_runs.create_index("created_at")
    await db.agent_runs.create_index("status")
    await db.agent_episodes.create_index("run_id", unique=True)
    await db.agent_episodes.create_index([("domain", 1), ("started_at", -1)])
    await db.agent_facts.create_index([("domain", 1), ("fact_key", 1)], unique=True)


async def close_db():
    global client
    if client:
        client.close()


def get_db():
    return client.rankengine
