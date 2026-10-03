"""In-memory Backend used by tests and the contract suite."""
import json
from typing import Any, Dict, Mapping, Optional, Tuple

from ..errors import NotConnected
from .base import (CONNECTED, NOT_CONNECTED, ActionResult, BackendEvent, Capabilities,
                   ConnectionInfo, ConnectSession, ProviderConfig)


class FakeBackend:
    def __init__(self) -> None:
        self.connections: Dict[Tuple[str, str], str] = {}
        self.calls: list = []
        self.fail_next: list = []  # exceptions raised by the next execute_action calls

    def capabilities(self) -> Capabilities:
        return Capabilities(named_actions=True, proxy=True)

    async def create_connect_session(self, user_id: str, provider: ProviderConfig, callback_url: str) -> ConnectSession:
        conn_id = f"fake_{user_id}_{provider.tool_type}"
        self.connections[(user_id, provider.tool_type)] = conn_id
        return ConnectSession(url=f"https://fake.example/connect/{conn_id}?cb={callback_url}", backend_connection_id=conn_id)

    async def get_connection(self, user_id: str, provider: ProviderConfig) -> ConnectionInfo:
        conn_id = self.connections.get((user_id, provider.tool_type))
        if not conn_id:
            return ConnectionInfo(status=NOT_CONNECTED)
        return ConnectionInfo(status=CONNECTED, backend_connection_id=conn_id, label="fake@example.com")

    async def disconnect(self, user_id: str, provider: ProviderConfig) -> None:
        self.connections.pop((user_id, provider.tool_type), None)

    async def execute_action(self, user_id: str, provider: ProviderConfig, action: str, args: Mapping[str, Any]) -> ActionResult:
        self.calls.append((user_id, action, dict(args)))
        if self.fail_next:
            raise self.fail_next.pop(0)
        if (user_id, provider.tool_type) not in self.connections:
            raise NotConnected(provider.tool_type)
        return ActionResult(ok=True, data={"action": action})

    async def proxy(self, user_id: str, provider: ProviderConfig, method: str, endpoint: str,
                    params: Optional[Mapping[str, Any]], body: Any) -> ActionResult:
        if (user_id, provider.tool_type) not in self.connections:
            raise NotConnected(provider.tool_type)
        return ActionResult(ok=True, data={"method": method, "endpoint": endpoint})

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> Optional[BackendEvent]:
        d = json.loads(body)
        return BackendEvent(event_id=d["id"], kind=d["kind"], backend_connection_id=d["connection"],
                            user_id=d.get("user"), toolkit_slug=d.get("toolkit"))
