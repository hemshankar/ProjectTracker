from motor.motor_asyncio import AsyncIOMotorClient

from . import config

_client = AsyncIOMotorClient(config.MONGO_URI)
db = _client[config.MONGO_DB_NAME]

boards_collection = db["boards"]
users_collection = db["users"]
agents_collection = db["agents"]
agent_members_collection = db["agent_members"]
board_shares_collection = db["board_shares"]
task_runs_collection = db["task_runs"]
audit_log_collection = db["audit_log"]
agent_settings_collection = db["agent_settings"]
tool_connections_collection = db["tool_connections"]
llm_calls_collection = db["llm_calls"]
resource_locks_collection = db["resource_locks"]
rate_limits_collection = db["rate_limits"]
global_settings_collection = db["global_settings"]
agent_links_collection = db["agent_links"]
labels_collection = db["labels"]
undo_pointers_collection = db["undo_pointers"]


async def ensure_indexes():
    await agent_members_collection.create_index(
        [("agentId", 1), ("userId", 1)], unique=True
    )
    await board_shares_collection.create_index(
        [("boardId", 1), ("userId", 1)], unique=True
    )
    await boards_collection.create_index("agentId")
    await users_collection.create_index("email", unique=True)
    await task_runs_collection.create_index([("boardId", 1), ("taskId", 1)])
    await audit_log_collection.create_index([("agentId", 1), ("ts", 1)])
    await audit_log_collection.create_index([("boardId", 1), ("ts", 1)])
    await audit_log_collection.create_index([("agentId", 1), ("actorId", 1), ("ts", -1)])
    await tool_connections_collection.create_index([("agentId", 1), ("toolType", 1)], unique=True)
    await llm_calls_collection.create_index([("boardId", 1)])
    await llm_calls_collection.create_index([("agentId", 1)])
    await llm_calls_collection.create_index([("runId", 1), ("ts", 1)])
    await llm_calls_collection.create_index([("parentRunId", 1)])
    # TTL purge (Phase 8) — `expiresAt` is computed per-document at insert
    # time from that Agent's configured retention window, so one index here
    # supports a per-Agent-configurable TTL rather than one fixed globally.
    await llm_calls_collection.create_index("expiresAt", expireAfterSeconds=0)
    await agent_links_collection.create_index([("fromAgentId", 1), ("toAgentId", 1)], unique=True)
    await task_runs_collection.create_index([("parentRunId", 1)])
    await boards_collection.create_index("tasks.delegatedFromTaskId")
    await labels_collection.create_index("name", unique=True)


def close_client() -> None:
    """Releases the driver's pooled sockets on app shutdown — otherwise a
    `--reload` restart leaves the outgoing process's connections open on
    Mongo's side until the OS eventually reaps them."""
    _client.close()
