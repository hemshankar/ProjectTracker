"""Response models for the usage API. Member models are deliberately minimal: totals only, so a
later change cannot leak model/user/call-kind breakdowns to non-admins by accident."""
from typing import List, Optional

from pydantic import BaseModel


class MemberTotal(BaseModel):
    usd: Optional[float] = None
    stale: bool = False


class BoardUsage(MemberTotal):
    calls: int = 0
    enabled: bool = True


class TaskUsage(BoardUsage):
    inputTokens: int = 0
    outputTokens: int = 0


class UsageBatch(BaseModel):
    totals: dict  # id -> usd (null when unknown)
    stale: bool = False
    enabled: bool = True  # False when the workspace hides this display; totals is then empty


class AdminTotals(BaseModel):
    usd: float = 0.0
    calls: int = 0
    inputTokens: int = 0
    outputTokens: int = 0
    cacheReadTokens: int = 0
    cacheCreationTokens: int = 0
    webSearchCount: int = 0
    pendingUsd: float = 0.0


class AdminBreakdownRow(AdminTotals):
    key: Optional[str] = None
    name: Optional[str] = None
    deleted: bool = False


class AdminSeriesPoint(AdminTotals):
    bucket: str
    bucketTs: int
    key: Optional[str] = None


class AdminRowsPage(BaseModel):
    rows: List[dict]
    nextCursor: Optional[str] = None


class UsageHealth(BaseModel):
    serviceReachable: bool
    outbox: dict
    delayThresholdSeconds: int = 900


class AlertOut(BaseModel):
    key: str
    severity: str
    title: str
    message: str
    status: str
    firstSeenAt: int
    lastSeenAt: int
    count: int
    acknowledgedAt: Optional[int] = None
    acknowledgedBy: Optional[str] = None
    resolvedAt: Optional[int] = None


class AlertSummary(BaseModel):
    unacknowledged: int
    severity: Optional[str] = None
