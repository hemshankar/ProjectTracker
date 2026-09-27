"""The `ToolConnector` interface every tool integration implements.

Open/Closed: adding a fourth tool means adding one new subclass in this
package and registering it in `registry.py` — never editing dispatch code
that calls connectors, here or in the execution loop.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ...models_tools import ConnectedTokens


class ToolConnector(ABC):
    tool_type: str

    @abstractmethod
    def configured(self) -> bool:
        """Whether this connector has the provider credentials it needs
        (client id/secret) to run a real OAuth flow at all."""

    @abstractmethod
    def build_authorize_url(self, state: str) -> str:
        ...

    @abstractmethod
    async def exchange_code(self, code: str) -> ConnectedTokens:
        ...

    @abstractmethod
    async def refresh(self, tokens: ConnectedTokens) -> ConnectedTokens:
        ...

    @abstractmethod
    async def execute(self, action: str, params: Dict[str, Any], tokens: Optional[ConnectedTokens]) -> str:
        """Perform the real side effect. `tokens` is None when the Agent
        hasn't connected this tool — callers are expected to have already
        decided a simulated fallback is acceptable before reaching here."""
