"""python -m app.accounting.reconcile.cli completeness [--window-hours N] [--repair]
python -m app.accounting.reconcile.cli counters [--repair]
`--repair` is the only thing that writes. Without it both commands are read-only."""
import argparse
import asyncio
import sys

from ..backfill_mongo import MongoNameResolver
from ..counters import SpendCounters
from ..outbox import OutboxRepository
from ..pending import PendingUsage
from ..query_client import AccountingUnavailable, HttpUsageQueryClient
from .completeness import LedgerCompletenessCheck
from .counters import CounterReconcile
from .probe import HttpLedgerProbe
from .sources import MongoCallSource


def build_completeness() -> LedgerCompletenessCheck:
    return LedgerCompletenessCheck(MongoCallSource(), HttpLedgerProbe(HttpUsageQueryClient()),
                                   OutboxRepository(), MongoNameResolver())


def build_counters() -> CounterReconcile:
    return CounterReconcile(SpendCounters(), HttpLedgerProbe(HttpUsageQueryClient()), PendingUsage())


async def _completeness(args) -> int:
    r = await build_completeness().run(window_hours=args.window_hours, repair=args.repair)
    print(f"checked={r.checked} missing={r.missing} missingUsd={r.missing_usd:.6f} repaired={r.repaired}")
    for call_id in r.missing_ids[:20]:
        print(f"  missing {call_id}")
    return 1 if r.missing > r.repaired else 0


async def _counters(args) -> int:
    r = await build_counters().run(repair=args.repair)
    print(f"checked={r.checked} drifting={len(r.drifts)} unmarked={len(r.unmarked)}")
    if r.unmarked:
        print("  unmarked (no seed marker, skipped; run `python -m app.accounting.cli seed-counters`): "
              + ", ".join(r.unmarked))
    for d in r.drifts:
        print(f"  {d.scope}: counter={d.counter:.6f} ledger={d.ledger:.6f} pending={d.pending:.6f} baseline={d.baseline:.6f} "
              f"delta={d.delta:.6f}{' REPAIRED' if d.repaired else ''}")
    return 1 if any(not d.repaired for d in r.drifts) else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.accounting.reconcile.cli")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("completeness")
    c.add_argument("--window-hours", type=int, help="default RECONCILE_WINDOW_HOURS")
    c.add_argument("--repair", action="store_true", help="re-enqueue missing rows")
    k = sub.add_parser("counters")
    k.add_argument("--repair", action="store_true", help="set drifting counters to ledger+pending (audited)")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_completeness(args) if args.command == "completeness" else _counters(args))
    except AccountingUnavailable as exc:
        print(f"accounting service unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
