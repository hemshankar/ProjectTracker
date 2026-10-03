from dataclasses import dataclass
from typing import Any, Optional

UNKNOWN_MODEL = "unknown"


@dataclass(frozen=True)
class UsageSnapshot:
    model: str = UNKNOWN_MODEL
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    web_search_count: int = 0
    request_id: Optional[str] = None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def usage_from_response(response: Any, requested_model: Optional[str] = None) -> UsageSnapshot:
    """Complete usage from an Anthropic message. Never raises: absent fields become 0/None."""
    usage = getattr(response, "usage", None)
    model = getattr(response, "model", None)
    request_id = getattr(response, "_request_id", None)
    server_tools = getattr(usage, "server_tool_use", None)
    return UsageSnapshot(
        model=model if isinstance(model, str) and model else (requested_model or UNKNOWN_MODEL),
        input_tokens=_int(getattr(usage, "input_tokens", 0)),
        output_tokens=_int(getattr(usage, "output_tokens", 0)),
        cache_read_tokens=_int(getattr(usage, "cache_read_input_tokens", 0)),
        cache_creation_tokens=_int(getattr(usage, "cache_creation_input_tokens", 0)),
        web_search_count=_int(getattr(server_tools, "web_search_requests", 0)),
        request_id=request_id if isinstance(request_id, str) else None,
    )
