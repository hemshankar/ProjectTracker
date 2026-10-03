"""Gates 1, 4: READ-ONLY audit of the live databases (never writes). Compares what users see, the ledger, and llm_calls."""
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

from .harness import REPO


def _key() -> str:
    for line in (REPO / "accounting-service" / ".env").read_text().splitlines():
        if line.startswith("ACCOUNTING_SERVICE_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("ACCOUNTING_SERVICE_KEY not found")


def _get(path: str, params: dict):
    req = urllib.request.Request(f"http://127.0.0.1:8200/internal{path}?{urllib.parse.urlencode(params)}",
                                 headers={"X-Internal-Key": _key()})
    return json.load(urllib.request.urlopen(req, timeout=10))


async def audit(r) -> None:
    print("Live audit (read-only): gates 1 and 4", flush=True)
    mongo = AsyncIOMotorClient("mongodb://localhost:27017")
    calls, ledger = mongo["scatterboard"]["llm_calls"], mongo["scatterboard_accounting"]["usage_ledger"]
    n_calls, n_ledger = await calls.count_documents({}), await ledger.count_documents({})
    s_calls = sum([d["usd"] async for d in calls.aggregate([{"$group": {"_id": None, "usd": {"$sum": "$usd"}}}])] or [0])
    s_ledger = sum([d["usd"] async for d in ledger.aggregate([{"$group": {"_id": None, "usd": {"$sum": "$usd"}}}])] or [0])
    r.check("G1", "live: ledger count == llm_calls count", n_calls == n_ledger, f"{n_ledger} vs {n_calls}")
    r.check("G1", "live: ledger sum(usd) == llm_calls sum(usd)", abs(s_calls - s_ledger) < 1e-6, f"{s_ledger:.6f} vs {s_calls:.6f}")
    agents = [d["_id"] async for d in calls.aggregate([{"$group": {"_id": "$agentId", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 5}])]
    now = int(time.time() * 1000)
    for agent in agents:
        by = lambda coll: coll.aggregate([{"$match": {"agentId": agent}}, {"$group": {"_id": None, "usd": {"$sum": "$usd"}, "n": {"$sum": 1}}}])
        c = [d async for d in by(calls)][0]
        l = [d async for d in by(ledger)][0]
        shown = _get("/summary", {"agentId": agent, "since": now - 399 * 86_400_000, "until": now})  # what the UI reads
        ok = abs(shown["usd"] - l["usd"]) <= 0.005 and abs(l["usd"] - c["usd"]) <= 0.005 and shown["calls"] == l["n"] == c["n"]
        r.check("G4", f"workspace {agent}: UI total == ledger == llm_calls", ok,
                f"UI ${shown['usd']:.4f}/{shown['calls']} calls, ledger ${l['usd']:.4f}/{l['n']}, llm_calls ${c['usd']:.4f}/{c['n']}")
        boards = [d["_id"] async for d in calls.aggregate([{"$match": {"agentId": agent}}, {"$group": {"_id": "$boardId"}}])]
        bt = _get("/summary/batch", {"agentId": agent, "boardIds": ",".join(boards)})
        for b in boards:
            c_b = [d async for d in calls.aggregate([{"$match": {"boardId": b}}, {"$group": {"_id": None, "usd": {"$sum": "$usd"}}}])][0]["usd"]
            r.check("G4", f"  board {b}: board total == llm_calls", abs(bt[b]["usd"] - c_b) <= 0.005, f"${bt[b]['usd']:.4f} vs ${c_b:.4f}")
    mongo.close()
