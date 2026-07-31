from motor.motor_asyncio import AsyncIOMotorClient

client: AsyncIOMotorClient | None = None


async def connect_db(uri: str):
    global client
    client = AsyncIOMotorClient(uri)
    return client.rankengine


async def close_db():
    global client
    if client:
        client.close()


def get_db():
    return client.rankengine
