from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UsageAttribution:
    """Who/what a board-chat call is billed to (supplied by the route, which knows auth)."""

    user_id: Optional[str] = None
    task_id: Optional[str] = None


@dataclass(frozen=True)
class DispatchAttribution:
    """Board-level attribution for a dispatch-planner call; never split across tasks."""

    agent_id: Optional[str]
    board_id: str
    user_id: Optional[str] = None
