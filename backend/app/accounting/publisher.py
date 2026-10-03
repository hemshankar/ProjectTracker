"""Makes one finished call durable for accounting: outbox event + spend counters. Never raises."""
import logging
from typing import Optional

from .counters import SpendCounters
from .events import UsageEvent
from .fallback import FallbackWriter
from .outbox import OutboxRepository

log = logging.getLogger(__name__)


class UsagePublisher:
    def __init__(self, outbox: Optional[OutboxRepository] = None, counters: Optional[SpendCounters] = None,
                 fallback: Optional[FallbackWriter] = None):
        self._outbox = outbox or OutboxRepository()
        self._counters = counters or SpendCounters()
        self._fallback = fallback or FallbackWriter()

    async def publish(self, call_id: str, event: Optional[UsageEvent], agent_id: Optional[str],
                      board_id: Optional[str], usd: float) -> None:
        if event is not None:
            await self._enqueue(call_id, event)
        try:
            await self._counters.add(agent_id, board_id, usd)
        except Exception:
            log.exception("spend counter update failed for call %s", call_id)

    async def _enqueue(self, call_id: str, event: UsageEvent) -> None:
        payload = event.model_dump(mode="json")
        try:
            await self._outbox.enqueue(payload)
        except Exception:
            log.exception("usage outbox insert failed for call %s; writing fallback file", call_id)
            try:
                self._fallback.append(payload)
            except Exception:
                log.exception("usage fallback write failed for call %s; event only in llm_calls", call_id)
