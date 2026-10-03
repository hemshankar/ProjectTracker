"""Backend protocols + value objects. No vendor imports here."""
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol

CONNECTED = "connected"
NOT_CONNECTED = "not_connected"
EXPIRED = "expired"


@dataclass(frozen=True)
class ProviderConfig:
    tool_type: str
    display_name: str
    backend: str
    backend_slug: str
    auth_mode: str = "managed_oauth"
    enabled: bool = True


@dataclass(frozen=True)
class ConnectSession:
    url: str
    backend_connection_id: Optional[str] = None


@dataclass(frozen=True)
class ConnectionInfo:
    status: str
    backend_connection_id: Optional[str] = None
    label: Optional[str] = None


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Capabilities:
    named_actions: bool = True
    proxy: bool = False
    triggers: bool = False


@dataclass(frozen=True)
class BackendEvent:
    """Normalized inbound event. kind: connected | expired | removed."""

    event_id: str
    kind: str
    backend_connection_id: str
    user_id: Optional[str] = None
    toolkit_slug: Optional[str] = None
    timestamp: Optional[int] = None  # epoch seconds
    extra: Dict[str, Any] = field(default_factory=dict)


class Connectable(Protocol):
    async def create_connect_session(self, user_id: str, provider: ProviderConfig, callback_url: str) -> ConnectSession: ...
    async def get_connection(self, user_id: str, provider: ProviderConfig) -> ConnectionInfo: ...
    async def disconnect(self, user_id: str, provider: ProviderConfig) -> None: ...


class Actionable(Protocol):
    async def execute_action(self, user_id: str, provider: ProviderConfig, action: str, args: Mapping[str, Any]) -> ActionResult: ...
    async def proxy(self, user_id: str, provider: ProviderConfig, method: str, endpoint: str,
                    params: Optional[Mapping[str, Any]], body: Any) -> ActionResult: ...


class EventSource(Protocol):
    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> Optional[BackendEvent]: ...


class Backend(Connectable, Actionable, EventSource, Protocol):
    def capabilities(self) -> Capabilities: ...
