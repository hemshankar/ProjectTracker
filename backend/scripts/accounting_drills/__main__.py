"""python -m scripts.accounting_drills {scratch|live|all}   (run from backend/, DRILL_ACCOUNTING_PYTHON set)

scratch: gates 1-3, 5-7 in throwaway zz_drill_* databases plus a throwaway accounting service on :8299.
live:    gates 1 and 4 against the live databases, read-only."""
import asyncio
import sys

from . import harness

harness.configure_env()  # before anything imports `app`


async def run_scratch(r) -> None:
    from . import caps_perf, outage, traffic
    harness.guard()
    await harness.reset_databases()
    svc = harness.ScratchService()
    svc.start()
    try:
        await traffic.backfill(svc, r)
        await traffic.live_traffic(svc, r)
        await outage.outage(svc, r)
        await caps_perf.caps(r)
        await caps_perf.perf(r)
    finally:
        svc.stop()
        await harness.reset_databases()  # leave nothing behind


async def main(mode: str) -> int:
    r = harness.Results()
    if mode in ("live", "all"):
        from . import live_audit
        await live_audit.audit(r)
    if mode in ("scratch", "all"):
        await run_scratch(r)
    failed = [x for x in r.rows if not x[2]]
    print(f"\n{len(r.rows) - len(failed)}/{len(r.rows)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all")))
