"""Read-only aggregation for the task detail view: how many agents and
sub-agents have worked a task, each sub-agent's own nested conversation,
and — for a task that delegated part of its work to a peer Agent — that
peer's own conversation on its board, when the requesting user can see it.

A thin read layer over `task_runs` (this task's primary runs plus any
sub-agent runs parented to them) and `boards` (any task elsewhere tagged
`delegatedFromTaskId` back to this one).
"""
from fastapi import HTTPException

from ..database import agents_collection, boards_collection, task_runs_collection
from ..dependencies import get_board_role


def _find_task(board: dict, task_id: str) -> dict:
    task = next((t for t in board.get("tasks", []) if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _tagged_messages(board: dict, task_id: str) -> list:
    return [
        m for chat in board.get("chats", []) for m in chat.get("messages", [])
        if m.get("taskId") == task_id
    ]


def _subagent_run_json(run: dict) -> dict:
    return {
        "runId": run["_id"],
        "status": run.get("status"),
        "instructions": run.get("instructions"),
        "allowedTools": run.get("allowedTools"),
        "transcript": run.get("transcript") or [],
        "startedAt": run.get("startedAt"),
        "endedAt": run.get("endedAt"),
        "error": run.get("error"),
    }


async def _peer_delegations(task_id: str, user_id: str) -> list:
    out = []
    agent_names: dict = {}
    async for target_board in boards_collection.find({"tasks.delegatedFromTaskId": task_id}):
        for target_task in target_board.get("tasks", []):
            if target_task.get("delegatedFromTaskId") != task_id:
                continue
            to_agent_id = target_board.get("agentId")
            if to_agent_id not in agent_names:
                agent = await agents_collection.find_one({"_id": to_agent_id})
                agent_names[to_agent_id] = (agent or {}).get("name")
            role, _ = await get_board_role(target_board["_id"], user_id)
            accessible = role is not None
            out.append({
                "toAgentId": to_agent_id,
                "toAgentName": agent_names[to_agent_id],
                "targetBoardId": target_board["_id"],
                "targetTaskId": target_task["id"],
                "status": target_task.get("status"),
                "accessible": accessible,
                "messages": _tagged_messages(target_board, target_task["id"]) if accessible else [],
            })
    return out


async def get_task_activity(board_id: str, task_id: str, user_id: str) -> dict:
    board = await boards_collection.find_one({"_id": board_id})
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    _find_task(board, task_id)

    own_runs = [
        r async for r in task_runs_collection.find(
            {"boardId": board_id, "taskId": task_id, "kind": {"$ne": "subagent"}}
        )
    ]
    own_run_ids = [r["_id"] for r in own_runs]
    sub_runs = []
    if own_run_ids:
        sub_runs = [r async for r in task_runs_collection.find({"parentRunId": {"$in": own_run_ids}})]
    sub_runs.sort(key=lambda r: r.get("startedAt") or 0)

    peer = await _peer_delegations(task_id, user_id)

    return {
        "taskId": task_id,
        "messages": _tagged_messages(board, task_id),
        "counts": {
            "agents": 1 if own_runs else 0,
            "subAgents": len(sub_runs),
            "peerAgents": len(peer),
        },
        "subAgentRuns": [_subagent_run_json(r) for r in sub_runs],
        "peerDelegations": peer,
    }
