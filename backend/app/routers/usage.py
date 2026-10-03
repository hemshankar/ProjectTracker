"""Usage endpoints. Members: totals only. Admins: history. `agentId` always comes from the path or the
board document, never from a query parameter."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..accounting.query_client import HttpUsageQueryClient
from ..database import boards_collection
from ..dependencies import require_agent_admin, require_agent_member, require_board_access
from ..models_usage import (AdminBreakdownRow, AdminRowsPage, AdminSeriesPoint, AdminTotals, BoardUsage,
                            TaskUsage, UsageBatch, UsageHealth)
from ..services.usage_admin_service import UsageAdminService
from ..services.usage_service import UsageService

router = APIRouter(prefix="/api", tags=["usage"])

_client = HttpUsageQueryClient()
member_usage = UsageService(_client)
admin_usage = UsageAdminService(_client)


async def _board(board_id: str) -> dict:
    board = await boards_collection.find_one({"_id": board_id})
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@router.get("/boards/{board_id}/usage", response_model=BoardUsage)
async def board_usage(board_id: str, _u: dict = Depends(require_board_access("viewer"))):
    return await member_usage.board_usage(await _board(board_id))


@router.get("/boards/{board_id}/usage/tasks", response_model=UsageBatch)
async def board_task_usage(board_id: str, _u: dict = Depends(require_board_access("viewer"))):
    return await member_usage.tasks_batch(await _board(board_id))


@router.get("/boards/{board_id}/tasks/{task_id}/usage", response_model=TaskUsage)
async def task_usage(board_id: str, task_id: str, _u: dict = Depends(require_board_access("viewer"))):
    board = await _board(board_id)
    if not any(t.get("id") == task_id for t in board.get("tasks", [])):
        raise HTTPException(status_code=404, detail="Task not found")
    return await member_usage.task_usage(board, task_id)


@router.get("/agents/{agent_id}/usage/boards", response_model=UsageBatch)
async def agent_board_usage(agent_id: str, user: dict = Depends(require_agent_member())):
    return await member_usage.boards_batch(agent_id, user["_id"])


@router.get("/agents/{agent_id}/usage/summary", response_model=AdminTotals)
async def summary(agent_id: str, boardId: Optional[str] = None, taskId: Optional[str] = None,
                  since: Optional[int] = None, until: Optional[int] = None,
                  _a: dict = Depends(require_agent_admin())):
    return await admin_usage.summary(agent_id, dict(boardId=boardId, taskId=taskId, since=since, until=until))


@router.get("/agents/{agent_id}/usage/timeseries", response_model=list[AdminSeriesPoint])
async def timeseries(agent_id: str, granularity: str = "day", groupBy: str = "none",
                     boardId: Optional[str] = None, taskId: Optional[str] = None,
                     since: Optional[int] = None, until: Optional[int] = None,
                     _a: dict = Depends(require_agent_admin())):
    return await admin_usage.timeseries(agent_id, dict(granularity=granularity, groupBy=groupBy, boardId=boardId,
                                                       taskId=taskId, since=since, until=until))


@router.get("/agents/{agent_id}/usage/breakdown", response_model=list[AdminBreakdownRow])
async def breakdown(agent_id: str, groupBy: str = "board", limit: int = Query(20, ge=1, le=100),
                    boardId: Optional[str] = None, taskId: Optional[str] = None,
                    since: Optional[int] = None, until: Optional[int] = None,
                    _a: dict = Depends(require_agent_admin())):
    return await admin_usage.breakdown(agent_id, dict(groupBy=groupBy, limit=limit, boardId=boardId, taskId=taskId,
                                                      since=since, until=until))


_LEDGER_FILTERS = ("boardId", "taskId", "runId", "model", "userId", "callKind", "outcome", "since", "until")


def _ledger_params(q) -> dict:
    return {k: q.get(k) for k in _LEDGER_FILTERS}


@router.get("/agents/{agent_id}/usage/rows", response_model=AdminRowsPage)
async def rows(agent_id: str, boardId: Optional[str] = None, taskId: Optional[str] = None,
               runId: Optional[str] = None, model: Optional[str] = None, userId: Optional[str] = None,
               callKind: Optional[str] = None, outcome: Optional[str] = None, since: Optional[int] = None,
               until: Optional[int] = None, limit: int = Query(100, ge=1, le=500), cursor: Optional[str] = None,
               _a: dict = Depends(require_agent_admin())):
    params = _ledger_params(locals())
    return await admin_usage.rows(agent_id, {**params, "limit": limit, "cursor": cursor})


@router.get("/agents/{agent_id}/usage/export")
async def export(agent_id: str, format: str = Query("csv", pattern="^(csv|jsonl)$"),
                 boardId: Optional[str] = None, taskId: Optional[str] = None, model: Optional[str] = None,
                 userId: Optional[str] = None, callKind: Optional[str] = None, since: Optional[int] = None,
                 until: Optional[int] = None, _a: dict = Depends(require_agent_admin())):
    params = {"format": format, "boardId": boardId, "taskId": taskId, "model": model, "userId": userId,
              "callKind": callKind, "since": since, "until": until}
    headers, body = await admin_usage.export(agent_id, params)
    passthrough = {k: v for k, v in headers.items() if k.lower() == "content-disposition"}
    return StreamingResponse(body, media_type=headers.get("content-type", "text/csv"), headers=passthrough)


@router.get("/agents/{agent_id}/usage/health", response_model=UsageHealth)
async def health(agent_id: str, _a: dict = Depends(require_agent_admin())):
    return await admin_usage.health(agent_id)
