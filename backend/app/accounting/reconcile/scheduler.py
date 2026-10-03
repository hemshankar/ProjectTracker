"""Background reconcile jobs, same lifecycle pattern as OutboxWorker. A failing job never stops the loop.
Each job raises the alerts it finds and resolves the ones its own check says have cleared."""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

from ... import config
from ..query_client import AccountingUnavailable, UsageQueryClient
from . import alerts
from .alert_store import AlertStore
from .alerts import Alert

log = logging.getLogger(__name__)
TICK_SECONDS = 30


@dataclass
class Job:
    name: str
    interval: float
    run: Callable[[], Awaitable[None]]
    last_run: float = float("-inf")


class ReconcileScheduler:
    def __init__(self, completeness, counters, outbox, client: UsageQueryClient, store: AlertStore,
                 enabled: Optional[bool] = None, clock: Callable[[], float] = time.monotonic):
        self._enabled = config.RECONCILE_ENABLED if enabled is None else enabled
        self._client, self._outbox, self._store, self._clock = client, outbox, store, clock
        self._completeness, self._counters = completeness, counters
        self._watch = alerts.ServiceDownWatch()
        self._task: Optional[asyncio.Task] = None
        self.jobs: List[Job] = [
            Job("completeness", config.RECONCILE_COMPLETENESS_INTERVAL_SECONDS, self._check_completeness),
            Job("counters", config.RECONCILE_COUNTERS_INTERVAL_SECONDS, self._check_counters),
            Job("health", 60, self._check_health),
        ]

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="usage-reconcile")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def tick(self) -> List[str]:
        """Run every job that is due. Returns the names that ran. Exceptions are logged, not raised."""
        ran = []
        for job in self.jobs:
            if self._clock() - job.last_run < job.interval:
                continue
            job.last_run = self._clock()
            ran.append(job.name)
            try:
                await job.run()
            except AccountingUnavailable as exc:
                log.warning("reconcile job %s skipped, accounting unavailable: %s", job.name, exc)
            except Exception:
                log.exception("reconcile job %s failed", job.name)
        return ran

    async def _loop(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(TICK_SECONDS)

    async def _check_completeness(self) -> None:
        report = await self._completeness.run(repair=True)
        found = []
        if report.missing > report.repaired:
            found.append(Alert(alerts.COMPLETENESS_MISSING, "error", "Ledger is missing usage rows",
                               f"{report.missing - report.repaired} recent llm_calls row(s) have no ledger row "
                               "after a repair pass. Run `reconcile completeness --repair`."))
        await self._store.apply(found, [alerts.COMPLETENESS_MISSING])

    async def _check_counters(self) -> None:
        report = await self._counters.run(repair=False)
        found = []
        if report.drifts:
            scopes = ", ".join(d.scope for d in report.drifts[:5])
            found.append(Alert(alerts.COUNTER_DRIFT, "warning", "Spend counters disagree with the ledger",
                               f"{len(report.drifts)} counter(s) drifted beyond tolerance: {scopes}. "
                               "Run `reconcile counters` for details."))
        await self._store.apply(found, [alerts.COUNTER_DRIFT])

    async def _check_health(self) -> None:
        stats = await self._outbox.stats()
        log.info("usage outbox: %s", stats)
        reachable = await self._client.ping()
        found = alerts.outbox_alerts(stats)
        found.append(self._watch.observe(reachable, time.time()))
        found.append(await alerts.fallback_pricing_alert())
        managed = list(alerts.HEALTH_KEYS)
        if reachable:  # the service's own rollup check can only be read while it is up
            try:
                found.append(alerts.rollup_alert((await self._client.get("/stats", {})).get("rollupVerify")))
                managed.append(alerts.ROLLUP_MISMATCH)
            except AccountingUnavailable:
                pass
        await self._store.apply([a for a in found if a], managed)
