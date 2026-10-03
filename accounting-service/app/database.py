from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from . import config

LEDGER_COLLECTION = "usage_ledger"
ROLLUP_COLLECTION = "usage_daily"
_LEDGER_INDEX_FIELDS = ("agentId", "boardId", "taskId", "userId", "model", "callKind")


def get_database() -> AsyncIOMotorDatabase:
    return AsyncIOMotorClient(config.MONGO_URI)[config.MONGO_DB_NAME]


async def ensure_indexes(db) -> None:
    """Ledger indexes. Deliberately no TTL index: the ledger is permanent."""
    ledger = db[LEDGER_COLLECTION]
    for field in _LEDGER_INDEX_FIELDS:
        await ledger.create_index([(field, 1), ("ts", 1)])
    await ledger.create_index("ingestedAt")  # ingest-rate stat
    rollups = db[ROLLUP_COLLECTION]
    for field in ("agentId", "boardId", "userId", "model"):
        await rollups.create_index([(field, 1), ("dayTs", 1)])
    await rollups.create_index("taskId")
