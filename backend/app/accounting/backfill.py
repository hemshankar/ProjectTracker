"""Resumable backfill of legacy `llm_calls` into the accounting ledger."""
import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional, Protocol, Tuple

from .backfill_mapping import map_llm_call
from .client import SinkError, UsageSink

Cursor = Tuple[int, str]  # (ts, _id)


class LlmCallSource(Protocol):
    async def fetch_after(self, cursor: Optional[Cursor], limit: int,
                          since: Optional[int], until: Optional[int]) -> List[dict]: ...


class CheckpointStore(Protocol):
    async def load(self) -> Optional[Cursor]: ...
    async def save(self, cursor: Cursor) -> None: ...


class NameResolver(Protocol):
    async def resolve(self, row: dict) -> dict: ...


class BackfillAborted(Exception):
    pass


@dataclass
class BackfillReport:
    read: int = 0
    accepted: int = 0
    duplicates: int = 0
    rejected: int = 0
    usd_total: float = 0.0
    batches: int = 0
    rejections: List[dict] = field(default_factory=list)


class BackfillRunner:
    def __init__(self, source: LlmCallSource, sink: UsageSink, checkpoint: CheckpointStore,
                 names: NameResolver, batch_size: int = 500, max_failures: int = 5,
                 backoff_seconds: float = 1.0,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 log: Callable[[str], None] = print):
        self._source, self._sink, self._checkpoint, self._names = source, sink, checkpoint, names
        self._batch_size, self._max_failures = batch_size, max_failures
        self._backoff, self._sleep, self._log = backoff_seconds, sleep, log

    async def run(self, since: Optional[int] = None, until: Optional[int] = None,
                  dry_run: bool = False) -> BackfillReport:
        report = BackfillReport()
        cursor = None if dry_run else await self._checkpoint.load()
        while True:
            rows = await self._source.fetch_after(cursor, self._batch_size, since, until)
            if not rows:
                return report
            events = [map_llm_call(r, await self._names.resolve(r)) for r in rows]
            report.read += len(rows)
            report.usd_total += sum(e["usd"] for e in events)
            if not dry_run:
                result = await self._send_with_retry(events)
                report.accepted += result.accepted
                report.duplicates += result.duplicates
                report.rejected += len(result.rejected)
                report.rejections.extend(result.rejected)
            cursor = (rows[-1]["ts"], rows[-1]["_id"])
            if not dry_run:
                await self._checkpoint.save(cursor)
            report.batches += 1
            self._log(f"batch {report.batches}: read={report.read} accepted={report.accepted} "
                      f"duplicates={report.duplicates} rejected={report.rejected}")

    async def _send_with_retry(self, events: List[dict]):
        failures = 0
        while True:
            try:
                return await self._sink.send(events)
            except SinkError as exc:
                failures += 1
                if not exc.retryable or failures >= self._max_failures:
                    raise BackfillAborted(f"giving up after {failures} failure(s): {exc}") from exc
                await self._sleep(self._backoff * 2 ** (failures - 1))
