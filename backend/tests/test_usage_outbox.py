import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import asyncio

import pytest

from app import config
from app.accounting.client import SinkError, SinkResult
from app.accounting.counters import GLOBAL_SCOPE, SpendCounters, agent_scope, board_scope
from app.accounting.fallback import FallbackReplayer, FallbackWriter
from app.accounting.outbox import OutboxRepository
from app.accounting.publisher import UsagePublisher
from app.accounting.seed import seed_counters
from app.accounting.worker import OutboxWorker
from app.database import boards_collection, llm_calls_collection, spend_counters_collection, usage_outbox_collection
from app.models import now_ms
from app.services import budget_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

PFX = "ob-"
AGENT, BOARD = "ob-agent", "ob-board"


def event(i):
    return {"callId": f"{PFX}{i}", "ts": 1, "agentId": AGENT, "callKind": "task_run", "usd": 0.5}


async def clean():
    # Other tests' recorder calls also enqueue rows; the worker claims any due row, so start empty.
    await usage_outbox_collection.delete_many({})
    await spend_counters_collection.delete_many({"_id": {"$in": [board_scope(BOARD), agent_scope(AGENT)]}})
    await llm_calls_collection.delete_many({"boardId": BOARD})
    await boards_collection.delete_one({"_id": BOARD})


class FakeSink:
    def __init__(self, fail=False, rejected=()):
        self.fail, self.rejected, self.sent = fail, list(rejected), []

    async def send(self, events):
        if self.fail:
            raise SinkError("down")
        self.sent.extend(e["callId"] for e in events)
        return SinkResult(accepted=len(events), rejected=[{"callId": c, "reason": "bad"} for c in self.rejected])


async def test_enqueue_is_idempotent():
    await clean()
    repo = OutboxRepository()
    assert await repo.enqueue(event(1)) is True
    assert await repo.enqueue(event(1)) is False
    assert await usage_outbox_collection.count_documents({"_id": f"{PFX}1"}) == 1
    await clean()


async def test_worker_delivers_and_handles_rejects():
    await clean()
    repo, sink = OutboxRepository(), FakeSink(rejected=[f"{PFX}2"])
    for i in (1, 2, 3):
        await repo.enqueue(event(i))
    assert await OutboxWorker(repo, sink).run_once() == 3
    status = {d["_id"]: d["status"] async for d in usage_outbox_collection.find({"_id": {"$regex": f"^{PFX}"}})}
    assert status == {f"{PFX}1": "delivered", f"{PFX}2": "rejected", f"{PFX}3": "delivered"}
    assert await OutboxWorker(repo, sink).run_once() == 0  # rejected is not retried
    await clean()


async def test_outage_backs_off_then_drains():
    await clean()
    repo, sink = OutboxRepository(), FakeSink(fail=True)
    for i in range(5):
        await repo.enqueue(event(i))
    worker = OutboxWorker(repo, sink)
    assert await worker.run_once() == 5
    row = await usage_outbox_collection.find_one({"_id": f"{PFX}0"})
    assert row["status"] == "pending" and row["attempts"] == 1 and row["nextAttemptAt"] > now_ms()
    assert await worker.run_once() == 0  # not due yet
    await usage_outbox_collection.update_many({"_id": {"$regex": f"^{PFX}"}}, {"$set": {"nextAttemptAt": 0}})
    sink.fail = False
    assert await worker.run_once() == 5
    assert sorted(sink.sent) == [f"{PFX}{i}" for i in range(5)]
    await clean()


async def test_expired_lease_is_reclaimed():
    await clean()
    repo = OutboxRepository()
    await repo.enqueue(event(1))
    assert len(await repo.claim(10, 60_000)) == 1
    assert await repo.claim(10, 60_000) == []  # leased
    assert len(await repo.claim(10, 60_000, now=now_ms() + 120_000)) == 1
    await clean()


async def test_concurrent_counter_increments_are_exact():
    await clean()
    counters = SpendCounters()
    before = await counters.get(GLOBAL_SCOPE)
    await asyncio.gather(*[counters.add(AGENT, BOARD, 0.25) for _ in range(20)])
    assert await counters.get(board_scope(BOARD)) == pytest.approx(5.0)
    assert await counters.get(agent_scope(AGENT)) == pytest.approx(5.0)
    assert await counters.get(GLOBAL_SCOPE) == pytest.approx(before + 5.0)
    await spend_counters_collection.update_one({"_id": GLOBAL_SCOPE}, {"$inc": {"usd": -5.0}})
    await clean()


async def test_publisher_never_raises_and_uses_fallback(tmp_path):
    await clean()

    class BrokenOutbox:
        async def enqueue(self, e):
            raise RuntimeError("mongo down")

    class BrokenCounters:
        async def add(self, *a):
            raise RuntimeError("mongo down")

    path = str(tmp_path / "fb.jsonl")
    from app.accounting.events import UsageEvent
    ev = UsageEvent(callId=f"{PFX}9", ts=1, agentId=AGENT, callKind="task_run")
    await UsagePublisher(BrokenOutbox(), BrokenCounters(), FallbackWriter(path)).publish(f"{PFX}9", ev, AGENT, BOARD, 1.0)
    assert await FallbackReplayer(OutboxRepository(), path).replay() == 1
    assert await usage_outbox_collection.count_documents({"_id": f"{PFX}9"}) == 1
    assert not os.path.exists(path)
    await clean()


async def test_caps_counters_vs_legacy_and_seeding(monkeypatch):
    await clean()
    await boards_collection.insert_one({"_id": BOARD, "agentId": AGENT, "status": "running", "tasks": [],
                                        "budgetCapUsd": 1.0})
    await budget_service.record_llm_call(AGENT, BOARD, "t", "r", 0.6)
    await budget_service.record_llm_call(AGENT, BOARD, "t", "r", 0.4)
    monkeypatch.setattr(config, "SPEND_COUNTERS_ENFORCED", False)
    assert await budget_service.check_exceeded(AGENT, BOARD) == "budget_exceeded"
    monkeypatch.setattr(config, "SPEND_COUNTERS_ENFORCED", True)
    assert await budget_service.check_exceeded(AGENT, BOARD) is None  # counters not seeded yet
    counters = SpendCounters()
    await seed_counters(counters, dry_run=True)
    assert await counters.get(board_scope(BOARD)) == 0.0  # dry run wrote nothing
    await seed_counters(counters)
    await seed_counters(counters)  # idempotent: sets, never increments
    assert await counters.get(board_scope(BOARD)) == pytest.approx(1.0)
    assert await budget_service.check_exceeded(AGENT, BOARD) == "budget_exceeded"
    await clean()
