from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from . import config
from .connection_migration import migrate_connections


def get_database() -> AsyncIOMotorDatabase:
    return AsyncIOMotorClient(config.MONGO_URI)[config.MONGO_DB_NAME]


async def ensure_indexes(db) -> None:
    await db["providers"].create_index("toolType", unique=True)
    await migrate_connections(db)
    await db["audit_log"].create_index("at")
    await db["webhook_events"].create_index("eventId", unique=True)
    await db["webhook_events"].create_index("receivedAt", expireAfterSeconds=7 * 24 * 3600)
