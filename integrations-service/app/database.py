from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from . import config


def get_database() -> AsyncIOMotorDatabase:
    return AsyncIOMotorClient(config.MONGO_URI)[config.MONGO_DB_NAME]


async def ensure_indexes(db) -> None:
    await db["providers"].create_index("toolType", unique=True)
    await db["connections"].create_index([("agentId", 1), ("toolType", 1)], unique=True)
    await db["connections"].create_index("backendConnectionId")
    await db["audit_log"].create_index("at")
    await db["webhook_events"].create_index("eventId", unique=True)
    await db["webhook_events"].create_index("receivedAt", expireAfterSeconds=7 * 24 * 3600)
