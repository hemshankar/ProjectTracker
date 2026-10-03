"""Records a board-chat Anthropic call. Nothing here may raise into the user's reply."""
import logging
from typing import Any, Optional

from .attribution import UsageAttribution
from .events import CallKind, Outcome
from .recorder import get_recorder
from .usage_snapshot import usage_from_response

log = logging.getLogger(__name__)


def partial_message(stream: Any) -> Optional[Any]:
    """Whatever the stream has accumulated so far, or None when it has nothing billable."""
    try:
        snapshot = stream.current_message_snapshot
    except Exception:
        return None
    usage = usage_from_response(snapshot)
    return snapshot if (usage.input_tokens or usage.output_tokens) else None


async def record_chat_call(board: dict, attribution: Optional[UsageAttribution], response: Any,
                           system_prompt: str, messages: list, latency_ms: float, outcome: Outcome) -> None:
    attribution = attribution or UsageAttribution()
    try:
        text = "\n".join(b.text for b in getattr(response, "content", []) or [] if getattr(b, "type", "") == "text")
        await get_recorder().record(
            agent_id=board.get("agentId"), board_id=board["_id"], task_id=attribution.task_id, run_id=None,
            response=response, system_prompt=system_prompt, request_messages=messages, tool_call=None,
            latency_ms=latency_ms, response_text=text, call_kind=CallKind.CHAT.value,
            user_id=attribution.user_id, outcome=outcome,
        )
    except Exception:
        log.exception("failed to record chat usage for board %s", board.get("_id"))
