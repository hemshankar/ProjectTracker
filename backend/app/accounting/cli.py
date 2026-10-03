"""python -m app.accounting.cli backfill [--since MS --until MS --dry-run --batch-size N]
python -m app.accounting.cli seed-counters [--dry-run]"""
import argparse
import asyncio
import sys

from .backfill import BackfillAborted, BackfillRunner
from .backfill_mongo import MongoCheckpointStore, MongoLlmCallSource, MongoNameResolver
from .client import HttpUsageClient
from .counters import GLOBAL_SCOPE, SpendCounters
from .seed import seed_counters


async def _backfill(args) -> int:
    runner = BackfillRunner(MongoLlmCallSource(), HttpUsageClient(), MongoCheckpointStore(),
                            MongoNameResolver(), batch_size=args.batch_size)
    try:
        report = await runner.run(since=args.since, until=args.until, dry_run=args.dry_run)
    except BackfillAborted as exc:
        print(f"ABORTED: {exc} (progress is checkpointed; re-run to resume)", file=sys.stderr)
        return 1
    mode = "DRY RUN (nothing sent)" if args.dry_run else "DONE"
    print(f"{mode}: read={report.read} accepted={report.accepted} duplicates={report.duplicates} "
          f"rejected={report.rejected} totalUsd={report.usd_total:.6f}")
    for r in report.rejections[:20]:
        print(f"  rejected {r.get('callId')}: {r.get('reason')}")
    return 0


async def _seed_counters(args) -> int:
    totals = await seed_counters(SpendCounters(), dry_run=args.dry_run)
    mode = "DRY RUN (nothing written)" if args.dry_run else "SEEDED"
    print(f"{mode}: scopes={len(totals)} globalUsd={totals[GLOBAL_SCOPE]:.6f}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="app.accounting.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    bf = sub.add_parser("backfill", help="Send existing llm_calls rows to the accounting ledger")
    bf.add_argument("--since", type=int, help="epoch ms, inclusive")
    bf.add_argument("--until", type=int, help="epoch ms, inclusive")
    bf.add_argument("--batch-size", type=int, default=500)
    bf.add_argument("--dry-run", action="store_true", help="compute totals only; send nothing")
    sc = sub.add_parser("seed-counters", help="Set spend counters from the current sum of llm_calls")
    sc.add_argument("--dry-run", action="store_true", help="compute totals only; write nothing")
    args = parser.parse_args(argv)
    return asyncio.run(_seed_counters(args) if args.command == "seed-counters" else _backfill(args))


if __name__ == "__main__":
    sys.exit(main())
