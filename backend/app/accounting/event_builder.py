from typing import Optional

from ..pricing import PriceRates
from .context import UsageContext
from .events import CallKind, Outcome, Rates, Source, UsageEvent
from .usage_snapshot import UsageSnapshot


class UsageEventBuilder:
    def build(self, call_id: str, ts: int, snapshot: UsageSnapshot, context: UsageContext, rates: PriceRates,
              usd: float, priced_by_fallback: bool, latency_ms: Optional[float],
              outcome: Outcome = Outcome.SUCCESS) -> UsageEvent:
        return UsageEvent(
            callId=call_id, ts=ts,
            agentId=context.agent_id or "unknown", callKind=CallKind(context.call_kind),
            boardId=context.board_id, taskId=context.task_id, runId=context.run_id,
            parentRunId=context.parent_run_id, userId=context.user_id,
            agentName=context.agent_name, boardTitle=context.board_title, taskTitle=context.task_title,
            model=snapshot.model, inputTokens=snapshot.input_tokens, outputTokens=snapshot.output_tokens,
            cacheReadTokens=snapshot.cache_read_tokens, cacheCreationTokens=snapshot.cache_creation_tokens,
            webSearchCount=snapshot.web_search_count,
            rates=Rates(**rates.to_event_rates()), usd=usd, pricedByFallback=priced_by_fallback,
            latencyMs=latency_ms, outcome=outcome, anthropicRequestId=snapshot.request_id,
            source=Source.LIVE, estimated=False,
        )
