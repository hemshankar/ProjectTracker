"""llm_calls -> ledger completeness: every recent llm_calls row must have a ledger row (or be queued)."""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Protocol

from ... import config
from ..backfill_mapping import map_llm_call
from .probe import LedgerProbe

log = logging.getLogger(__name__)
PAGE = 1000


class CallSource(Protocol):
    async def page(self, since_ms: int, after_id: Optional[str], limit: int) -> List[dict]:
        """Slim rows (`_id`, `ts`, `usd`) in `_id` order within the window."""
        ...

    async def full(self, ids: List[str]) -> List[dict]: ...


class RepairQueue(Protocol):
    async def undelivered_ids(self, ids: List[str]) -> List[str]: ...
    async def requeue(self, event: dict) -> None: ...


class Names(Protocol):
    async def resolve(self, row: dict) -> dict: ...


@dataclass
class CompletenessReport:
    checked: int = 0
    missing: int = 0
    missing_usd: float = 0.0
    repaired: int = 0
    missing_ids: List[str] = field(default_factory=list)


class LedgerCompletenessCheck:
    def __init__(self, source: CallSource, probe: LedgerProbe, queue: RepairQueue, names: Names,
                 clock: Callable[[], float] = time.time):
        self._source, self._probe, self._queue, self._names, self._clock = source, probe, queue, names, clock

    async def run(self, window_hours: Optional[int] = None, repair: bool = False) -> CompletenessReport:
        since = int(self._clock() * 1000) - (window_hours or config.RECONCILE_WINDOW_HOURS) * 3_600_000
        report, after = CompletenessReport(), None
        while True:
            rows = await self._source.page(since, after, PAGE)
            if not rows:
                break
            after = rows[-1]["_id"]
            report.checked += len(rows)
            ids = [r["_id"] for r in rows]
            queued = set(await self._queue.undelivered_ids(ids))
            gone = [i for i in await self._probe.missing(ids) if i not in queued]
            usd = {r["_id"]: r.get("usd") or 0.0 for r in rows}
            report.missing += len(gone)
            report.missing_usd += sum(usd[i] for i in gone)
            report.missing_ids.extend(gone)
            if repair and gone:
                report.repaired += await self._repair(gone)
        log.log(logging.ERROR if report.missing else logging.INFO,
                "ledger completeness: checked=%d missing=%d missingUsd=%.6f repaired=%d",
                report.checked, report.missing, report.missing_usd, report.repaired)
        return report

    async def _repair(self, ids: List[str]) -> int:
        fixed = 0
        for row in await self._source.full(ids):
            await self._queue.requeue(map_llm_call(row, await self._names.resolve(row)))
            fixed += 1
        return fixed
