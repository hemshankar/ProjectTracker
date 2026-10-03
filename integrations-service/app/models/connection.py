"""Connection value objects. Frozen; services pass these instead of dicts."""
from dataclasses import dataclass
from typing import Optional

PENDING = "pending"


@dataclass(frozen=True)
class ConnectionRef:
    """Addresses one connection. connection_id=None means "the default for agent+tool"."""

    agent_id: str
    tool_type: str
    connection_id: Optional[str] = None


@dataclass(frozen=True)
class ConnectionRecord:
    connection_id: str
    agent_id: str
    tool_type: str
    backend: str
    backend_user_id: str  # the user_id sent to the backend; legacy rows keep agent_id
    status: str = PENDING
    label: Optional[str] = None
    owner_user_id: Optional[str] = None  # None = shared with the whole agent
    is_default: bool = False
    backend_connection_id: Optional[str] = None
    created_at: int = 0

    @property
    def visibility(self) -> str:
        return "owner" if self.owner_user_id else "agent"

    def visible_to(self, user_id: Optional[str]) -> bool:
        return self.owner_user_id is None or self.owner_user_id == user_id


@dataclass(frozen=True)
class SessionResult:
    url: str
    connection_id: str
