"""Core counters vs the ledger. Warns on drift; writes only with explicit repair (audited)."""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Tuple

from ...services.audit_service import write_audit
from ..counters import GLOBAL_SCOPE, SpendCounters
from ..pending import PendingUsage
from .probe import LedgerProbe

log = logging.getLogger(__name__)
ABS_TOLERANCE = 0.01
REL_TOLERANCE = 0.001


def parse_scope(scope: str) -> Tuple[str, Optional[str], Optional[str]]:
    """'board:b1' -> ('board', 'b1', 'boardId'); 'global' -> ('global', None, None)."""
    if scope == GLOBAL_SCOPE:
        return "global", None, None
    kind, _, ident = scope.partition(":")
    return kind, ident, {"board": "boardId", "agent": "agentId"}[kind]


def within_tolerance(counter: float, expected: float) -> bool:
    return abs(counter - expected) <= max(ABS_TOLERANCE, REL_TOLERANCE * expected)


class AuditSink(Protocol):
    async def __call__(self, scope: str, before: float, after: float) -> None: ...


async def audit_counter_repair(scope: str, before: float, after: float) -> None:
    await write_audit(agent_id=None, board_id=None, entity_type="spend_counter", action="update",
                      actor_type="human", actor_id="cli:reconcile",
                      before={"scope": scope, "usd": before}, after={"scope": scope, "usd": after})


@dataclass
class Drift:
    scope: str
    counter: float
    ledger: float
    pending: float
    baseline: float = 0.0
    repaired: bool = False

    @property
    def expected(self) -> float:
        return self.baseline + self.ledger + self.pending

    @property
    def delta(self) -> float:
        return round(self.counter - self.expected, 6)


@dataclass
class CounterReport:
    checked: int = 0
    drifts: List[Drift] = field(default_factory=list)
    unmarked: List[str] = field(default_factory=list)  # counters with no seed marker: cannot be compared


class CounterReconcile:
    def __init__(self, counters: SpendCounters, probe: LedgerProbe, pending: PendingUsage,
                 audit=audit_counter_repair):
        self._counters, self._probe, self._pending, self._audit = counters, probe, pending, audit

    async def run(self, repair: bool = False) -> CounterReport:
        """Expected counter = seed baseline + ledger since `seededAt` + undelivered outbox since then.
        (The ledger also holds older backfilled spend that counters never included, hence the cut-off.)"""
        report = CounterReport()
        for scope, doc in (await self._counters.all()).items():
            if doc["seededAt"] is None:
                report.unmarked.append(scope)
                continue
            kind, ident, field_name = parse_scope(scope)
            ledger = await self._probe.total(kind, ident, doc["seededAt"])
            pending = await self._pending.since_total(field_name, ident, doc["seededAt"])
            report.checked += 1
            drift = Drift(scope, doc["usd"], ledger, pending, doc["seedUsd"])
            if within_tolerance(drift.counter, drift.expected):
                continue
            log.warning("spend counter drift: scope=%s counter=%.6f ledger=%.6f pending=%.6f delta=%.6f",
                        scope, drift.counter, ledger, pending, drift.delta)
            if repair:
                await self._audit(scope, drift.counter, drift.expected)
                await self._counters.correct(scope, drift.expected)
                drift.repaired = True
            report.drifts.append(drift)
        if report.unmarked:
            log.warning("%d spend counter(s) have no seed marker and were skipped; run `cli seed-counters` "
                        "to baseline them: %s", len(report.unmarked), report.unmarked)
        return report
