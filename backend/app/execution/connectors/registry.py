from typing import Dict

from .base import ToolConnector
from .calendar import CalendarConnector
from .gmail import GmailConnector
from .slack import SlackConnector

_CONNECTORS: Dict[str, ToolConnector] = {
    "gmail": GmailConnector(),
    "calendar": CalendarConnector(),
    "slack": SlackConnector(),
}


def get_connector(tool_type: str) -> ToolConnector:
    connector = _CONNECTORS.get(tool_type)
    if connector is None:
        raise ValueError(f"Unknown tool type: {tool_type}")
    return connector
