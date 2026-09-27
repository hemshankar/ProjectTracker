"""Token-bucket rate limiting per (Agent, tool). A task that hits its limit
waits rather than failing (see `execution/enforcement.py`); this module only
owns the bucket math.
"""
from .. import config
from ..database import agent_settings_collection, rate_limits_collection
from ..models import now_ms
from ..models_settings import TOOL_TYPES


async def capacity_for(agent_id: str, tool_type: str) -> int:
    settings = await agent_settings_collection.find_one({"_id": agent_id}, {"rateLimits": 1})
    configured = (settings or {}).get("rateLimits", {}).get(tool_type, {}).get("capacityPerDay")
    if configured is not None:
        return configured
    return config.DEFAULT_RATE_LIMIT_PER_DAY.get(tool_type, 50)


async def try_consume(agent_id: str, tool_type: str) -> bool:
    if tool_type not in TOOL_TYPES:
        return True

    capacity = await capacity_for(agent_id, tool_type)
    doc_id = f"{agent_id}:{tool_type}"
    now = now_ms()
    doc = await rate_limits_collection.find_one({"_id": doc_id})

    if doc is None:
        tokens_after = capacity - 1
        await rate_limits_collection.insert_one(
            {"_id": doc_id, "tokens": tokens_after, "lastRefill": now}
        )
        return tokens_after >= 0

    refill_rate = capacity / config.RATE_LIMIT_WINDOW_MS
    elapsed = max(0, now - doc["lastRefill"])
    tokens = min(capacity, doc["tokens"] + elapsed * refill_rate)

    if tokens < 1:
        await rate_limits_collection.update_one({"_id": doc_id}, {"$set": {"tokens": tokens, "lastRefill": now}})
        return False

    await rate_limits_collection.update_one(
        {"_id": doc_id}, {"$set": {"tokens": tokens - 1, "lastRefill": now}}
    )
    return True
