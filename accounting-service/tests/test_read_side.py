import csv
import io
from datetime import datetime, timezone

import pytest

from app import cli, config
from app.database import ROLLUP_COLLECTION
from app.services.export_service import safe_cell
from app.services.query_service import bucket_start
from app.models.queries import Granularity
from .conftest import make_event


def ms(y, m, d, h=12):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


EVENTS = [
    make_event("e1", ts=ms(2026, 1, 30), usd=1.0, boardId="b1", taskId="t1", model="m1", boardTitle="Board One"),
    make_event("e2", ts=ms(2026, 1, 31, 23), usd=2.0, boardId="b1", taskId="t2", model="m2"),
    make_event("e3", ts=ms(2026, 2, 1, 0), usd=4.0, boardId="b2", taskId="t3", model="m1", callKind="chat"),
    make_event("e4", ts=ms(2026, 2, 2), usd=8.0, boardId="b2", taskId="t3", model="m1", userId="u1"),
    make_event("other", ts=ms(2026, 2, 2), usd=100.0, agentId="a2", boardId="b9", taskId="t9"),
]


async def post(client, auth, events=EVENTS):
    r = await client.post("/internal/events", json={"schemaVersion": 1, "events": events}, headers=auth)
    assert r.status_code == 200
    return r


async def get(client, auth, path, **params):
    return await client.get(f"/internal/{path}", params={"agentId": "a1", **params}, headers=auth)


async def test_rollups_idempotent_on_redelivery(client, auth, container):
    await post(client, auth)
    first = (await get(client, auth, "summary")).json()
    await post(client, auth)
    assert (await get(client, auth, "summary")).json() == first
    assert first["usd"] == 15.0 and first["calls"] == 4


async def test_summary_scopes_and_range(client, auth):
    await post(client, auth)
    assert (await get(client, auth, "summary", boardId="b1")).json()["usd"] == 3.0
    assert (await get(client, auth, "summary", taskId="t3")).json()["usd"] == 12.0
    r = (await get(client, auth, "summary", since=ms(2026, 2, 1), until=ms(2026, 2, 28))).json()
    assert r["usd"] == 12.0


async def test_scope_safety(client, auth):
    await post(client, auth)
    # board b9 belongs to agent a2; asking as a1 yields nothing
    assert (await get(client, auth, "summary", boardId="b9")).json()["usd"] == 0
    assert (await get(client, auth, "rows", boardId="b9")).json()["rows"] == []
    for path in ("summary", "summary/batch", "timeseries", "breakdown", "rows", "export"):
        assert (await client.get(f"/internal/{path}", headers=auth)).status_code == 422


async def test_batch_summary(client, auth):
    await post(client, auth)
    r = (await get(client, auth, "summary/batch", boardIds="b1,b2,nope")).json()
    assert r["b1"]["usd"] == 3.0 and r["b2"]["usd"] == 12.0 and r["nope"]["usd"] == 0
    assert "b9" not in r


async def test_timeseries_day_week_month_boundaries(client, auth):
    await post(client, auth)
    days = (await get(client, auth, "timeseries", granularity="day")).json()
    assert [(p["bucket"], p["usd"]) for p in days] == [
        ("2026-01-30", 1.0), ("2026-01-31", 2.0), ("2026-02-01", 4.0), ("2026-02-02", 8.0)]
    months = (await get(client, auth, "timeseries", granularity="month")).json()
    assert [(p["bucket"], p["usd"]) for p in months] == [("2026-01-01", 3.0), ("2026-02-01", 12.0)]
    weeks = (await get(client, auth, "timeseries", granularity="week")).json()
    # 2026-01-30 is a Friday, 02-01 a Sunday, 02-02 a Monday
    assert [(p["bucket"], p["usd"]) for p in weeks] == [("2026-01-26", 7.0), ("2026-02-02", 8.0)]
    grouped = (await get(client, auth, "timeseries", granularity="month", groupBy="model")).json()
    assert {(p["bucket"], p["key"]): p["usd"] for p in grouped} == {
        ("2026-01-01", "m1"): 1.0, ("2026-01-01", "m2"): 2.0, ("2026-02-01", "m1"): 12.0}


def test_bucket_start_week_is_monday():
    assert bucket_start(ms(2026, 2, 1, 0), Granularity.WEEK) == ms(2026, 1, 26, 0)


async def test_breakdown_with_names(client, auth):
    await post(client, auth)
    rows = (await get(client, auth, "breakdown", groupBy="board")).json()
    assert [(r["key"], r["usd"]) for r in rows] == [("b2", 12.0), ("b1", 3.0)]
    assert {r["key"]: r["name"] for r in rows}["b1"] == "Board One"
    by_kind = (await get(client, auth, "breakdown", groupBy="callKind")).json()
    assert {r["key"]: r["usd"] for r in by_kind} == {"task_run": 11.0, "chat": 4.0}


async def test_rows_keyset_pagination_with_equal_ts(client, auth):
    evs = [make_event(f"r{i}", ts=ms(2026, 3, 1)) for i in range(5)] + [make_event("r5", ts=ms(2026, 3, 2))]
    await post(client, auth, evs)
    seen, cursor = [], None
    while True:
        page = (await get(client, auth, "rows", limit=2, **({"cursor": cursor} if cursor else {}))).json()
        seen += [r["callId"] for r in page["rows"]]
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert sorted(seen) == [f"r{i}" for i in range(6)] and len(seen) == 6
    assert seen[0] == "r5"  # newest first


async def test_bounds(client, auth):
    assert (await get(client, auth, "rows", limit=501)).status_code == 400
    assert (await get(client, auth, "rows", limit=0)).status_code == 422
    over = (config.MAX_QUERY_RANGE_DAYS + 1) * 86_400_000
    assert (await get(client, auth, "rows", since=0, until=over)).status_code == 400
    assert (await get(client, auth, "export", since=0, until=over)).status_code == 400
    assert (await get(client, auth, "export")).status_code == 400  # range required
    assert (await get(client, auth, "rows", cursor="garbage")).status_code == 400


async def test_rebuild_and_verify(client, auth, container):
    await post(client, auth)
    lo, hi = ms(2026, 1, 1), ms(2026, 3, 1)
    assert await container.rollups.verify(lo, hi) == []
    await container.db[ROLLUP_COLLECTION].update_one({"day": "2026-02-02", "agentId": "a1"}, {"$inc": {"usd": 5}})
    bad = await container.rollups.verify(lo, hi)
    assert [m["day"] for m in bad] == ["2026-02-02"] and bad[0]["delta"] == 5.0
    await container.rollups.rebuild(lo, hi)
    assert await container.rollups.verify(lo, hi) == []
    assert (await get(client, auth, "summary")).json()["usd"] == 15.0


async def test_cli_commands(client, auth, container, capsys):
    await post(client, auth)
    assert await cli.run(cli.parse(["ledger", "stats"]), container) == 0
    assert "count=5" in capsys.readouterr().out
    assert await cli.run(cli.parse(["rollups", "rebuild", "--from", "2026-01-01", "--to", "2026-03-01"]), container) == 0
    assert await cli.run(cli.parse(["rollups", "verify"]), container) == 0


async def test_export_csv(client, auth):
    evs = [make_event("x1", ts=ms(2026, 3, 1), taskTitle='=HYPERLINK("evil")'),
           make_event("x2", ts=ms(2026, 3, 2), boardTitle='has, comma "quote"')]
    await post(client, auth, evs)
    r = await get(client, auth, "export", format="csv", since=ms(2026, 3, 1, 0), until=ms(2026, 3, 3))
    assert "attachment" in r.headers["content-disposition"] and ".csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [x["callId"] for x in rows] == ["x1", "x2"]
    assert rows[0]["taskTitle"].startswith("'=") and rows[1]["boardTitle"] == 'has, comma "quote"'
    assert rows[0]["tsIso"] == "2026-03-01T12:00:00.000Z"


async def test_export_header_present_when_empty_and_jsonl(client, auth):
    r = await get(client, auth, "export", since=0, until=1000)
    assert r.text.startswith("callId,ts,tsIso") and len(r.text.strip().splitlines()) == 1
    await post(client, auth, [make_event("j1", ts=ms(2026, 3, 1))])
    r = await get(client, auth, "export", format="jsonl", since=ms(2026, 3, 1, 0), until=ms(2026, 3, 2))
    assert r.text.count("\n") == 1 and '"callId":"j1"' in r.text


async def test_export_streams_in_chunks(container, monkeypatch):
    calls = []

    class FakeLedger:
        async def iter_chunks(self, q, size):
            for i in range(3):
                calls.append(i)
                yield [{"_id": f"c{i}", "ts": 1000 + i}]

    from app.models.queries import LedgerFilter
    from app.services.export_service import ExportService
    _, _, stream = ExportService(FakeLedger()).prepare(LedgerFilter("a1", since_ms=0, until_ms=10), "csv")
    parts = [p async for p in stream]
    assert len(parts) == 4 and calls == [0, 1, 2]  # header + one part per chunk


def test_safe_cell():
    assert safe_cell("=1+1") == "'=1+1" and safe_cell("@x") == "'@x" and safe_cell("-5") == "'-5"
    assert safe_cell("plain") == "plain" and safe_cell(3) == 3


async def test_ledger_insert_failure_free_when_rollup_breaks(client, auth, container, monkeypatch):
    async def boom(_):
        raise RuntimeError("rollup down")
    monkeypatch.setattr(container.rollups, "apply", boom)
    r = await post(client, auth, [make_event("z1", ts=ms(2026, 3, 1))])
    assert r.json()["accepted"] == 1
