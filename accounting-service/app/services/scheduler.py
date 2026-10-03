"""Daily ledger-vs-rollup verification. Alerts (error log) on mismatch; repair stays explicit (`rollups rebuild`)."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import config
from .rollup_keys import DAY_MS
from .rollup_service import RollupService

log = logging.getLogger(__name__)


def seconds_until_hour(now: datetime, hour_utc: int) -> float:
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


class RollupVerifyScheduler:
    def __init__(self, rollups: RollupService, hour_utc: Optional[int] = None, lookback_days: Optional[int] = None,
                 enabled: Optional[bool] = None):
        self._rollups = rollups
        self._hour = config.ROLLUP_VERIFY_HOUR_UTC if hour_utc is None else hour_utc
        self._lookback = lookback_days or config.ROLLUP_VERIFY_LOOKBACK_DAYS
        self._enabled = config.ROLLUP_VERIFY_ENABLED if enabled is None else enabled
        self._task: Optional[asyncio.Task] = None
        self.last_result: Optional[dict] = None  # {at, mismatchedDays}; surfaced by /internal/stats

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="rollup-verify")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def run_once(self, now_ms: Optional[int] = None) -> int:
        """Returns mismatched day count. Never raises."""
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        try:
            bad = await self._rollups.verify(now_ms - self._lookback * DAY_MS, now_ms + 1)
        except Exception:
            log.exception("rollup verify failed")
            return -1
        self.last_result = {"at": now_ms, "mismatchedDays": len(bad)}
        if bad:
            log.error("ALERT rollup verify: %d day(s) mismatch, run `rollups rebuild`: %s", len(bad), bad[:5])
        else:
            log.info("rollup verify: ok")
        return len(bad)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(seconds_until_hour(datetime.now(timezone.utc), self._hour))
            await self.run_once()
