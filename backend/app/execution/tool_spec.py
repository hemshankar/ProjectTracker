from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    mutating: bool
    simulate: Callable[[Dict[str, Any]], str]
    tool_type: Optional[str] = None  # None for internal, non-connector tools
    resource_key: Optional[Callable[[Dict[str, Any]], str]] = None
