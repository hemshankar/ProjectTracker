"""Single entry point every call site uses to record an Anthropic call.

Price it, insert the `llm_calls` row, build the usage event, then hand it to the
publisher (outbox + spend counters). Only the `llm_calls` insert may raise.
"""
import logging
from typing import Any, Optional

from .. import pricing
from ..services import budget_service
from .context import UsageContext, UsageContextResolver
from .event_builder import UsageEventBuilder
from .events import Outcome, UsageEvent
from .publisher import UsagePublisher
from .usage_snapshot import UsageSnapshot, usage_from_response

log = logging.getLogger(__name__)


def infer_call_kind(parent_run_id: Optional[str]) -> str:
    return "subagent" if parent_run_id else "task_run"


class UsageRecorder:
    def __init__(self, resolver: Optional[UsageContextResolver] = None,
                 builder: Optional[UsageEventBuilder] = None, publisher: Optional[UsagePublisher] = None):
        self._resolver = resolver or UsageContextResolver()
        self._builder = builder or UsageEventBuilder()
        self._publisher = publisher or UsagePublisher()

    async def record(self, *, agent_id: Optional[str], board_id: str, task_id: Optional[str],
                     run_id: Optional[str], response: Any, system_prompt: str, request_messages: list,
                     tool_call: Optional[dict], latency_ms: float, response_text: str,
                     parent_run_id: Optional[str] = None, call_kind: Optional[str] = None,
                     user_id: Optional[str] = None, outcome: Outcome = Outcome.SUCCESS) -> dict:
        """Returns the inserted `llm_calls` doc. Only that insert may raise (as before);
        attribution, event building, outbox and counters never do."""
        kind = call_kind or infer_call_kind(parent_run_id)
        snap = usage_from_response(response)
        rates, by_fallback = pricing.rates_for(snap.model)
        usd = pricing.cost(snap.input_tokens, snap.output_tokens, snap.cache_read_tokens,
                           snap.cache_creation_tokens, snap.web_search_count, rates)
        context = await self._safe_context(agent_id, board_id, task_id, run_id, parent_run_id, kind, user_id)

        doc = await budget_service.record_llm_call(
            agent_id, board_id, task_id, run_id, usd,
            parent_run_id=parent_run_id, system_prompt=system_prompt, request_messages=request_messages,
            response_text=response_text, tool_call=tool_call,
            input_tokens=snap.input_tokens, output_tokens=snap.output_tokens, latency_ms=latency_ms,
            extra={"model": snap.model, "cacheReadTokens": snap.cache_read_tokens,
                   "cacheCreationTokens": snap.cache_creation_tokens, "webSearchCount": snap.web_search_count,
                   "callKind": kind, "rates": rates.to_event_rates(), "pricedByFallback": by_fallback,
                   "requestId": snap.request_id, "userId": context.user_id, "outcome": outcome.value},
        )
        event = self._safe_event(doc, snap, context, rates, usd, by_fallback, latency_ms, outcome)
        await self._publisher.publish(doc["_id"], event, agent_id, board_id, usd)
        return doc

    async def _safe_context(self, agent_id, board_id, task_id, run_id, parent_run_id, kind, user_id) -> UsageContext:
        try:
            return await self._resolver.resolve(agent_id=agent_id, board_id=board_id, task_id=task_id,
                                                run_id=run_id, parent_run_id=parent_run_id,
                                                call_kind=kind, user_id=user_id)
        except Exception:
            log.exception("usage context lookup failed; recording without name snapshots")
            return UsageContext(agent_id, board_id, task_id, run_id, parent_run_id, kind, user_id=user_id)

    def _safe_event(self, doc, snap: UsageSnapshot, context, rates, usd, by_fallback, latency_ms,
                    outcome: Outcome) -> Optional[UsageEvent]:
        try:
            return self._builder.build(doc["_id"], doc["ts"], snap, context, rates, usd, by_fallback, latency_ms, outcome)
        except Exception:
            log.exception("usage event build failed for call %s", doc.get("_id"))
            return None


_shared: Optional[UsageRecorder] = None


def get_recorder() -> UsageRecorder:
    """The one recorder every call site shares (so its name cache is shared too)."""
    global _shared
    if _shared is None:
        _shared = UsageRecorder()
    return _shared
