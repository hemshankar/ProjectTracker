import asyncio
import time

from app.accounting.outbox import OutboxRepository
from app.accounting.query_client import HttpUsageQueryClient
from app.accounting.recorder import get_recorder
from app.database import boards_collection

from .harness import fake_response

KINDS = ["task_run", "subagent", "chat", "dispatch"]


async def ledger_total(scope="global", ident=None, since=None) -> dict:
    return await HttpUsageQueryClient(timeout=10).get("/ledger/total", {"scope": scope, "id": ident, "since": since})


async def drain(timeout: float = 60.0) -> bool:
    repo, end = OutboxRepository(), time.monotonic() + timeout
    while time.monotonic() < end:
        if (await repo.stats())["pending"] == 0:
            return True
        await asyncio.sleep(0.2)
    return False


async def make_board(board_id: str, agent_id: str = "A", cap: float = None) -> None:
    doc = {"_id": board_id, "agentId": agent_id, "title": f"Board {board_id}", "tasks": [{"id": "T", "text": "Task"}]}
    if cap is not None:
        doc["budgetCapUsd"] = cap
    await boards_collection.replace_one({"_id": board_id}, doc, upsert=True)


async def record(kind: str, board: str, agent: str = "A", i: int = 0, inp: int = 1200, out: int = 300) -> dict:
    return await get_recorder().record(
        agent_id=agent, board_id=board, task_id="T", run_id=f"run{i}", response=fake_response(inp=inp, out=out),
        system_prompt="s", request_messages=[], tool_call=None, latency_ms=12.0, response_text="ok",
        parent_run_id=f"run{i}" if kind == "subagent" else None, call_kind=kind, user_id="U")
