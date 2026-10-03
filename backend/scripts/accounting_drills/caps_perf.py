"""Gates 6 and 7: cap drill (chat/dispatch count, no TTL decay) and latency/scaling measurements."""
import statistics
import time

from app import config
from app.accounting.recorder import get_recorder
from app.database import llm_calls_collection
from app.models import now_ms
from app.services import budget_service

from .common import make_board, record
from .harness import fake_response


async def caps(r) -> None:
    print("Gate 6: cap drill", flush=True)
    for kind in ("chat", "dispatch"):
        board = f"CAP-{kind}"
        await make_board(board, cap=0.0001)
        r.check("G6", f"{kind}: under the cap before any spend", await budget_service.check_exceeded("A", board) is None)
        await record(kind, board, inp=2000, out=500)
        r.check("G6", f"a single {kind} call counts toward the cap", await budget_service.check_exceeded("A", board) == "budget_exceeded")
    board = "CAP-chat"
    await llm_calls_collection.delete_many({"boardId": board})  # what the 90-day TTL purge does
    r.check("G6", "cap still holds after llm_calls rows expire (cumulative)", await budget_service.check_exceeded("A", board) == "budget_exceeded")
    config.SPEND_COUNTERS_ENFORCED = False
    try:
        decayed = await budget_service.check_exceeded("A", board) is None
    finally:
        config.SPEND_COUNTERS_ENFORCED = True
    r.check("G6", "(contrast) the legacy mode forgets the same spend", decayed, "legacy path sums llm_calls and sees 0")


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


async def _timed(coro_fn, n):
    out = []
    for i in range(n):
        t = time.perf_counter()
        await coro_fn(i)
        out.append((time.perf_counter() - t) * 1000)
    return out


async def perf(r) -> None:
    print("Gate 7: load check", flush=True)
    await make_board("PERF")
    n = 1000
    rec = get_recorder()
    full = await _timed(lambda i: record("task_run", "PERF", i=i), n)

    async def bare(i):  # the pre-accounting cost: just the llm_calls insert
        await budget_service.record_llm_call("A", "PERF", "T", f"r{i}", 0.001, input_tokens=1, output_tokens=1)
    base = await _timed(bare, n)
    added = _pct(full, 0.95) - _pct(base, 0.95)
    r.check("G7", "UsageRecorder.record added latency p95 < 5 ms", added < 5.0,
            f"record p50={statistics.median(full):.2f} p95={_pct(full, .95):.2f} ms; baseline insert p95={_pct(base, .95):.2f} ms; added p95={added:.2f} ms")
    await _cap_scaling(r)


async def _cap_scaling(r) -> None:
    async def grow(total):
        have = await llm_calls_collection.count_documents({"boardId": "SCALE"})
        docs = [{"_id": f"sc-{have + i}", "agentId": "A", "boardId": "SCALE", "usd": 0.00001, "ts": now_ms(),
                 "expiresAt": now_ms() + 10**10} for i in range(total - have)]
        for i in range(0, len(docs), 10000):
            await llm_calls_collection.insert_many(docs[i:i + 10000])

    await make_board("SCALE", cap=10**6)
    times = {}
    for rows in (10_000, 100_000):
        await grow(rows)
        for mode in (True, False):
            config.SPEND_COUNTERS_ENFORCED = mode
            t = await _timed(lambda _i: budget_service.check_exceeded("A", "SCALE"), 15)
            times[(rows, mode)] = statistics.median(t)
    config.SPEND_COUNTERS_ENFORCED = True
    flat = times[(100_000, True)] < max(5.0, times[(10_000, True)] * 3)
    r.check("G7", "cap check is constant-time at 10x data", flat,
            f"counters: {times[(10_000, True)]:.2f} ms @10k rows, {times[(100_000, True)]:.2f} ms @100k rows")
    r.check("G7", "(contrast) legacy cap check grows with data", times[(100_000, False)] > times[(10_000, False)] * 3,
            f"legacy: {times[(10_000, False)]:.1f} ms @10k, {times[(100_000, False)]:.1f} ms @100k")
