"""Alert conditions. Each returns `Alert`s; AlertStore persists them for the alerts page and bell."""
from dataclasses import dataclass
from typing import List, Optional

from ... import config
from ...database import usage_outbox_collection
from ...models import now_ms

_HOUR_MS = 3_600_000

OUTBOX_BACKLOG = "outbox_backlog"
OUTBOX_REJECTED = "outbox_rejected"
SERVICE_DOWN = "service_down"
PRICING_FALLBACK = "pricing_fallback"
ROLLUP_MISMATCH = "rollup_mismatch"
COMPLETENESS_MISSING = "completeness_missing"
COUNTER_DRIFT = "counter_drift"

HEALTH_KEYS = (OUTBOX_BACKLOG, OUTBOX_REJECTED, SERVICE_DOWN, PRICING_FALLBACK)


@dataclass(frozen=True)
class Alert:
    key: str        # stable id: one open alert per condition, however often it fires
    severity: str   # "error" | "warning"
    title: str
    message: str


def outbox_alerts(stats: dict) -> List[Alert]:
    out = []
    if stats.get("oldestPendingAgeSeconds", 0) > config.ALERT_OUTBOX_AGE_SECONDS:
        out.append(Alert(OUTBOX_BACKLOG, "error", "Usage delivery is backed up",
                         f"Oldest pending usage event is {stats['oldestPendingAgeSeconds']}s old; "
                         f"{stats.get('pending', 0)} waiting."))
    if stats.get("rejected", 0):
        out.append(Alert(OUTBOX_REJECTED, "error", "Usage events rejected",
                         f"{stats['rejected']} usage event(s) were rejected by the accounting service."))
    return out


def fallback_ratio_alert(total: int, fallback: int) -> Optional[Alert]:
    if total >= config.ALERT_FALLBACK_MIN_EVENTS and fallback / total > config.ALERT_FALLBACK_RATIO:
        return Alert(PRICING_FALLBACK, "warning", "Costs priced by fallback",
                     f"{fallback} of {total} usage events in the last hour used the fallback price. "
                     "The price table is stale or a new model is in use.")
    return None


async def fallback_pricing_alert() -> Optional[Alert]:
    base = {"event.ts": {"$gte": now_ms() - _HOUR_MS}}
    total = await usage_outbox_collection.count_documents(base)
    fallback = await usage_outbox_collection.count_documents({**base, "event.pricedByFallback": True})
    return fallback_ratio_alert(total, fallback)


def rollup_alert(verify: Optional[dict]) -> Optional[Alert]:
    if verify and verify.get("mismatchedDays"):
        return Alert(ROLLUP_MISMATCH, "error", "Rollups disagree with the ledger",
                     f"{verify['mismatchedDays']} day(s) differ. Run `rollups rebuild` in the accounting service.")
    return None


class ServiceDownWatch:
    """Alerts once the accounting service has been unreachable longer than the threshold."""

    def __init__(self):
        self._down_since: Optional[float] = None

    def observe(self, reachable: bool, now_s: float) -> Optional[Alert]:
        if reachable:
            self._down_since = None
            return None
        self._down_since = self._down_since if self._down_since is not None else now_s
        down_for = now_s - self._down_since
        if down_for > config.ALERT_SERVICE_DOWN_SECONDS:
            return Alert(SERVICE_DOWN, "error", "Accounting service unreachable",
                         f"The accounting service has been unreachable for {int(down_for)}s. "
                         "New usage is queued and will be delivered on recovery.")
        return None
