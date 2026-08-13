import asyncio
from backend.db.mongo import get_db, connect_db
from backend.config import settings

async def f():
    await connect_db(settings.mongodb_uri)
    doc = await get_db().sandbox_snapshots.find_one({}, sort=[("_id", -1)])
    print(doc["dom"])

if __name__ == "__main__":
    asyncio.run(f())
