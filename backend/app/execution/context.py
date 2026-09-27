from typing import Any, Dict, List, Optional

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
            "kind": "primary",
        }
    )
    return run_id


async def finish_task_run(run_id: str, status: str, error: Optional[str] = None) -> None:
    await task_runs_collection.update_one(
        {"_id": run_id}, {"$set": {"status": status, "endedAt": now_ms(), "error": error}}
    )


async def start_subagent_run(
    board_id: str,
    task_id: str,
    agent_id: Optional[str],
    parent_run_id: str,
    instructions: str,
    allowed_tools: Optional[List[str]],
) -> str:
    """A `delegate_subtask` invocation's own record — `parentRunId` links it
    back to the task run that spawned it, so the task detail view can list
    every sub-agent that has worked a task, not just the primary run."""
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
            "parentRunId": parent_run_id,
            "kind": "subagent",
            "instructions": instructions,
            "allowedTools": allowed_tools,
            "transcript": [],
        }
    )
    return run_id


async def finish_subagent_run(
    run_id: str, status: str, transcript: List[Dict[str, Any]], error: Optional[str] = None
) -> None:
    await task_runs_collection.update_one(
        {"_id": run_id},
        {"$set": {"status": status, "endedAt": now_ms(), "error": error, "transcript": transcript}},
    )
