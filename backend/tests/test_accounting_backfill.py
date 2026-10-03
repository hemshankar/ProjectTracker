from app.accounting.backfill import BackfillAborted, BackfillRunner
from app.accounting.backfill_mapping import map_llm_call
from app.accounting.client import SinkError, SinkResult

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


def row(i, **kw):
    return {"_id": f"c{i}", "ts": 1000 + i, "agentId": "a", "boardId": "b", "taskId": "t",
            "runId": "r", "parentRunId": None, "usd": 0.01 * i, "inputTokens": 10,
            "outputTokens": 5, "latencyMs": 12.0, **kw}


class FakeSource:
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: (r["ts"], r["_id"]))

    async def fetch_after(self, cursor, limit, since, until):
        out = [r for r in self.rows if cursor is None or (r["ts"], r["_id"]) > tuple(cursor)]
        return out[:limit]


class FakeCheckpoint:
    def __init__(self):
        self.cursor = None

    async def load(self):
        return self.cursor

    async def save(self, cursor):
        self.cursor = cursor


class FakeNames:
    async def resolve(self, r):
        return {"agentName": "Ws", "boardTitle": None, "taskTitle": None}


class FakeSink:
    def __init__(self, fail_times=0, retryable=True):
        self.fail_times, self.retryable, self.seen, self.calls = fail_times, retryable, set(), 0

    async def send(self, events):
        self.calls += 1
        if self.fail_times:
            self.fail_times -= 1
            raise SinkError("boom", self.retryable)
        new = [e for e in events if e["callId"] not in self.seen]
        self.seen.update(e["callId"] for e in new)
        return SinkResult(accepted=len(new), duplicates=len(events) - len(new))


async def _nosleep(_):
    pass


def runner(source, sink, cp=None, **kw):
    return BackfillRunner(source, sink, cp or FakeCheckpoint(), FakeNames(), sleep=_nosleep,
                          log=lambda _: None, **kw)


def test_mapping_copies_usd_and_infers_kind():
    e = map_llm_call(row(3), {"agentName": "W"})
    assert e["usd"] == 0.03 and e["callKind"] == "task_run" and e["model"] == "unknown"
    assert e["estimated"] is True and e["source"] == "backfill" and e["llmCallRef"] == "c3"
    assert e["cacheReadTokens"] == 0 and e["rates"]["input"] > 0 and e["agentName"] == "W"
    assert map_llm_call(row(1, parentRunId="p"))["callKind"] == "subagent"


def test_mapping_not_estimated_with_snapshot():
    e = map_llm_call(row(1, model="claude-haiku-4-5", rates={"input": 1, "output": 5}))
    assert e["estimated"] is False and e["model"] == "claude-haiku-4-5" and e["rates"]["input"] == 1


async def test_runner_batches_checkpoints_and_is_idempotent():
    src, sink, cp = FakeSource([row(i) for i in range(1, 6)]), FakeSink(), FakeCheckpoint()
    rep = await runner(src, sink, cp, batch_size=2).run()
    assert rep.read == 5 and rep.accepted == 5 and rep.batches == 3
    assert abs(rep.usd_total - 0.15) < 1e-9 and cp.cursor == (1005, "c5")
    # Fresh checkpoint (full re-run): everything is a duplicate.
    rep2 = await runner(src, sink, FakeCheckpoint(), batch_size=2).run()
    assert rep2.accepted == 0 and rep2.duplicates == 5


async def test_runner_resumes_from_checkpoint():
    src, sink, cp = FakeSource([row(i) for i in range(1, 5)]), FakeSink(), FakeCheckpoint()
    cp.cursor = (1002, "c2")
    rep = await runner(src, sink, cp).run()
    assert rep.read == 2 and sink.seen == {"c3", "c4"}


async def test_transient_failure_is_retried():
    sink = FakeSink(fail_times=2)
    rep = await runner(FakeSource([row(1)]), sink).run()
    assert rep.accepted == 1 and sink.calls == 3


async def test_aborts_after_repeated_failures_without_checkpointing():
    cp = FakeCheckpoint()
    with pytest.raises(BackfillAborted):
        await runner(FakeSource([row(1)]), FakeSink(fail_times=99), cp, max_failures=3).run()
    assert cp.cursor is None


async def test_non_retryable_aborts_immediately():
    sink = FakeSink(fail_times=99, retryable=False)
    with pytest.raises(BackfillAborted):
        await runner(FakeSource([row(1)]), sink).run()
    assert sink.calls == 1


async def test_dry_run_sends_nothing():
    sink, cp = FakeSink(), FakeCheckpoint()
    rep = await runner(FakeSource([row(1), row(2)]), sink, cp).run(dry_run=True)
    assert sink.calls == 0 and cp.cursor is None and rep.read == 2 and abs(rep.usd_total - 0.03) < 1e-9
