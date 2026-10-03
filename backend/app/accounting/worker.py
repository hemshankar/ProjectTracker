"""Background delivery of outbox rows to the accounting service."""
import asyncio
import logging
import random
import time
from typing import Optional

from .. import config
from ..models import now_ms
from .client import SinkError, UsageSink
from .outbox import OutboxRepository

log = logging.getLogger(__name__)
STATS_LOG_INTERVAL_SECONDS = 60


def backoff_seconds(attempts: int, cap: int) -> float:
    return min(2 ** attempts, cap) * random.uniform(0.8, 1.2)


class OutboxWorker:
    def __init__(self, repo: OutboxRepository, sink: UsageSink):
        self._repo, self._sink = repo, sink
        self._task: Optional[asyncio.Task] = None
        self._last_stats = 0.0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="usage-outbox-worker")

    async def stop(self) -> None:
        """Rows mid-batch keep their lease and are reclaimed later, so nothing is lost."""
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                worked = await self.run_once()
                await self._maybe_log_stats()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("outbox worker iteration failed")
                worked = 0
            if not worked:
                await asyncio.sleep(config.OUTBOX_POLL_SECONDS)

    async def run_once(self) -> int:
        """Deliver one batch. Returns the number of rows handled."""
        rows = await self._repo.claim(config.OUTBOX_BATCH_SIZE, config.OUTBOX_LEASE_SECONDS * 1000)
        if not rows:
            return 0
        try:
            result = await self._sink.send([r["event"] for r in rows])
        except SinkError as exc:
            await self._retry_all(rows, str(exc))
            return len(rows)
        rejected = {r.get("callId"): r.get("reason", "rejected") for r in result.rejected}
        for call_id, reason in rejected.items():
            await self._repo.mark_rejected(call_id, reason)
            log.error("usage event %s rejected by accounting service: %s", call_id, reason)
        await self._repo.mark_delivered([r["_id"] for r in rows if r["_id"] not in rejected])
        return len(rows)

    async def _retry_all(self, rows: list, error: str) -> None:
        # Any SinkError (including 4xx like a wrong service key) is retried: a config fix
        # should drain the queue, never poison it. Per-event rejects are handled separately.
        for row in rows:
            delay = backoff_seconds(row.get("attempts", 0) + 1, config.OUTBOX_MAX_BACKOFF_SECONDS)
            await self._repo.reschedule(row["_id"], error, now_ms() + int(delay * 1000))
        log.warning("usage delivery failed (%s); %d event(s) rescheduled", error, len(rows))

    async def _maybe_log_stats(self) -> None:
        if time.monotonic() - self._last_stats >= STATS_LOG_INTERVAL_SECONDS:
            self._last_stats = time.monotonic()
            log.info("usage outbox: %s", await self._repo.stats())
