from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class Granularity(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class GroupBy(str, Enum):
    """API dimension -> rollup field."""

    BOARD = "board"
    TASK = "task"
    MODEL = "model"
    USER = "user"
    CALL_KIND = "callKind"
    NONE = "none"

    @property
    def field(self) -> Optional[str]:
        return {"board": "boardId", "task": "taskId", "model": "model",
                "user": "userId", "callKind": "callKind"}.get(self.value)


@dataclass(frozen=True)
class UsageQuery:
    """Scope + range for rollup queries. `agentId` is always required."""

    agent_id: str
    board_id: Optional[str] = None
    task_id: Optional[str] = None
    since_ms: Optional[int] = None
    until_ms: Optional[int] = None


@dataclass(frozen=True)
class LedgerFilter:
    agent_id: str
    board_id: Optional[str] = None
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    model: Optional[str] = None
    user_id: Optional[str] = None
    call_kind: Optional[str] = None
    outcome: Optional[str] = None
    since_ms: Optional[int] = None
    until_ms: Optional[int] = None


class Totals(BaseModel):
    usd: float = 0.0
    calls: int = 0
    inputTokens: int = 0
    outputTokens: int = 0
    cacheReadTokens: int = 0
    cacheCreationTokens: int = 0
    webSearchCount: int = 0


class SeriesPoint(Totals):
    bucket: str
    bucketTs: int
    key: Optional[str] = None


class BreakdownRow(Totals):
    key: Optional[str] = None
    name: Optional[str] = None


class RowsPage(BaseModel):
    rows: List[dict]
    nextCursor: Optional[str] = None
