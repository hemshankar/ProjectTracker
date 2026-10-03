from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CallKind(str, Enum):
    TASK_RUN = "task_run"
    SUBAGENT = "subagent"
    CHAT = "chat"
    DISPATCH = "dispatch"


class Outcome(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class Source(str, Enum):
    LIVE = "live"
    BACKFILL = "backfill"


class Rates(BaseModel):
    """Rates applied at call time: $/MTok per token type, $/search for web search."""

    model_config = ConfigDict(frozen=True)

    input: float = 0.0
    output: float = 0.0
    cacheRead: float = 0.0
    cacheWrite: float = 0.0
    webSearch: float = 0.0


class UsageEvent(BaseModel):
    """One Anthropic call. `callId` becomes the ledger `_id`."""

    model_config = ConfigDict(frozen=True)

    callId: str = Field(min_length=1)
    ts: int = Field(ge=0, description="Call time, epoch ms")
    # scope
    agentId: str = Field(min_length=1)
    callKind: CallKind
    boardId: Optional[str] = None
    taskId: Optional[str] = None
    runId: Optional[str] = None
    parentRunId: Optional[str] = None
    userId: Optional[str] = None
    # name snapshots
    agentName: Optional[str] = None
    boardTitle: Optional[str] = None
    taskTitle: Optional[str] = None
    # usage
    model: str = "unknown"
    inputTokens: int = Field(default=0, ge=0)
    outputTokens: int = Field(default=0, ge=0)
    cacheReadTokens: int = Field(default=0, ge=0)
    cacheCreationTokens: int = Field(default=0, ge=0)
    webSearchCount: int = Field(default=0, ge=0)
    # pricing
    rates: Rates = Rates()
    usd: float = Field(default=0.0, ge=0)
    pricedByFallback: bool = False
    # outcome
    latencyMs: Optional[float] = None
    outcome: Outcome = Outcome.SUCCESS
    anthropicRequestId: Optional[str] = None
    # provenance
    source: Source = Source.LIVE
    estimated: bool = False
    llmCallRef: Optional[str] = None


class EventBatch(BaseModel):
    """`events` stay raw dicts so one malformed event cannot fail the batch."""

    schemaVersion: int
    events: List[dict]


class RejectedEvent(BaseModel):
    callId: Optional[str] = None
    reason: str


class IngestResult(BaseModel):
    accepted: int = 0
    duplicates: int = 0
    rejected: List[RejectedEvent] = []
