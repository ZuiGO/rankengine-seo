from neo4j import AsyncGraphDatabase, AsyncDriver

driver: AsyncDriver | None = None


async def connect_neo4j(uri: str, user: str, password: str):
    global driver
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    await driver.verify_connectivity()
    return driver


async def close_neo4j():
    global driver
    if driver:
        await driver.close()


def get_driver():
    return driver
