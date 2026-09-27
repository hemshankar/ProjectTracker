from typing import Optional

from ..database import task_runs_collection
from ..models import new_id, now_ms


async def start_task_run(board_id: str, task_id: str, agent_id: Optional[str]) -> str:
    run_id = new_id()
    await task_runs_collection.insert_one(
        {
            "_id": run_id,
            "boardId": board_id,
            "taskId": task_id,
            "agentId": agent_id,
            "status": "running",
            "startedAt": now_ms(),
            "endedAt": None,
            "error": None,
            "parentRunId": None,
        }
    )
    return run_id


async def finish_task_run(run_id: str, status: str, error: Optional[str] = None) -> None:
    await task_runs_collection.update_one(
        {"_id": run_id}, {"$set": {"status": status, "endedAt": now_ms(), "error": error}}
    )
