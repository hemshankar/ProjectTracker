"""Idempotent startup migration for the `connections` collection (multi-connection support)."""
import uuid

_OLD_INDEX_KEYS = [("agentId", 1), ("toolType", 1)]


async def backfill(col) -> int:
    """Legacy rows become the shared default connection; backendUserId stays the agent id so
    nothing is reconnected at the provider. Re-runnable: rows with a connectionId are skipped."""
    count = 0
    async for doc in col.find({"connectionId": {"$exists": False}}):
        await col.update_one({"_id": doc["_id"]}, {"$set": {
            "connectionId": f"conn_{uuid.uuid4().hex[:16]}", "ownerUserId": None, "visibility": "agent",
            "isDefault": True, "backendUserId": doc["agentId"]}})
        count += 1
    return count


async def swap_indexes(col) -> None:
    """The old unique agentId+toolType index blocks a second account; replace it."""
    info = await col.index_information()
    for name, spec in info.items():
        if spec.get("key") == _OLD_INDEX_KEYS and "partialFilterExpression" not in spec:
            await col.drop_index(name)
    await col.create_index("connectionId", unique=True)
    await col.create_index([("agentId", 1), ("toolType", 1)], unique=True, name="uniq_default_per_tool",
                           partialFilterExpression={"isDefault": True})
    await col.create_index([("agentId", 1), ("ownerUserId", 1)])
    await col.create_index("backendConnectionId")
    await col.create_index("backendUserId")


async def migrate_connections(db) -> None:
    col = db["connections"]
    await backfill(col)
    await swap_indexes(col)
