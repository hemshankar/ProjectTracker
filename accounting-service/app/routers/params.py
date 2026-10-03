"""Query-param dependencies shared by the read routers (HTTP translation only)."""
from typing import Optional

from fastapi import Query

from ..models.queries import LedgerFilter, UsageQuery


def usage_query(agentId: str = Query(..., min_length=1), boardId: Optional[str] = None,
                taskId: Optional[str] = None, since: Optional[int] = None,
                until: Optional[int] = None) -> UsageQuery:
    return UsageQuery(agentId, boardId, taskId, since, until)


def ledger_filter(agentId: str = Query(..., min_length=1), boardId: Optional[str] = None,
                  taskId: Optional[str] = None, runId: Optional[str] = None, model: Optional[str] = None,
                  userId: Optional[str] = None, callKind: Optional[str] = None,
                  outcome: Optional[str] = None, since: Optional[int] = None,
                  until: Optional[int] = None) -> LedgerFilter:
    return LedgerFilter(agentId, boardId, taskId, runId, model, userId, callKind, outcome, since, until)
