"""Compare-and-swap lock per external resource (e.g. `gmail:alice@x.com`,
`calendar:standup|2026-01-05T09:00`), so two runs can never take conflicting
actions on the same resource at once. Same CAS pattern as `transition_task_status`:
a filter miss just means the lock is unavailable, no separate locking primitive.
"""
from pymongo.errors import DuplicateKeyError

from .. import config
from ..database import resource_locks_collection
from ..models import now_ms


async def try_acquire(resource_key: str, run_id: str, ttl_ms: int = config.RESOURCE_LOCK_TTL_MS) -> bool:
    now = now_ms()
    try:
        await resource_locks_collection.find_one_and_update(
            {"_id": resource_key, "expiresAt": {"$lt": now}},
            {"$set": {"heldBy": run_id, "expiresAt": now + ttl_ms}},
            upsert=True,
        )
        return True
    except DuplicateKeyError:
        return False


async def release(resource_key: str, run_id: str) -> None:
    await resource_locks_collection.delete_one({"_id": resource_key, "heldBy": run_id})
