"""Operator commands:
  python -m app.cli rollups rebuild --from 2026-01-01 --to 2026-10-03
  python -m app.cli rollups verify  [--from ... --to ...]
  python -m app.cli ledger stats
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone

from .container import Container, get_container


def _day_ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


async def _range(c: Container, args) -> tuple:
    """Defaults to the ledger's full span. `--to` is inclusive of that whole day."""
    stats = await c.ledger.stats({})
    if not stats["count"]:
        return 0, 0
    lo = _day_ms(args.from_) if args.from_ else stats["minTs"]
    hi = _day_ms(args.to) + 86_400_000 if args.to else stats["maxTs"] + 1
    return lo, hi


async def run(args, c: Container) -> int:
    if args.group == "ledger":
        s = await c.ledger.stats({})
        print(f"count={s['count']} minTs={s['minTs']} maxTs={s['maxTs']} totalUsd={round(s['usd'], 6)}")
        return 0
    lo, hi = await _range(c, args)
    if args.action == "rebuild":
        print(f"rebuilt {await c.rollups.rebuild(lo, hi)} rollup documents")
        return 0
    bad = await c.rollups.verify(lo, hi)
    for m in bad:
        print(f"MISMATCH {m['day']}: ledger={m['ledgerUsd']} rollup={m['rollupUsd']} delta={m['delta']}")
    print("verify: OK, no mismatches" if not bad else f"verify: {len(bad)} day(s) mismatched")
    return 1 if bad else 0


def parse(argv=None):
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="group", required=True)
    r = sub.add_parser("rollups")
    r.add_argument("action", choices=["rebuild", "verify"])
    r.add_argument("--from", dest="from_", help="YYYY-MM-DD (UTC)")
    r.add_argument("--to", help="YYYY-MM-DD (UTC, inclusive)")
    l = sub.add_parser("ledger")
    l.add_argument("action", choices=["stats"])
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(parse(), get_container())))
