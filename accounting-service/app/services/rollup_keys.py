"""Pure helpers shared by live rollup updates, rebuild, and verify."""
from datetime import datetime, timezone
from typing import Dict, Iterable, List

DAY_MS = 86_400_000
DIMENSIONS = ("agentId", "boardId", "taskId", "model", "userId", "callKind")
SUM_FIELDS = ("inputTokens", "outputTokens", "cacheReadTokens", "cacheCreationTokens",
              "webSearchCount", "usd")


def day_start_ms(ts_ms: int) -> int:
    return ts_ms - ts_ms % DAY_MS


def day_string(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def rollup_id(day: str, ledger_doc: dict) -> str:
    parts = [day] + [str(ledger_doc.get(d) or "-") for d in DIMENSIONS]
    return "|".join(parts)


class RollupAccumulator:
    """Groups ledger docs in memory into rollup documents (one per key)."""

    def __init__(self):
        self._docs: Dict[str, dict] = {}

    def add(self, ledger_doc: dict) -> None:
        ts = ledger_doc["ts"]
        day = day_string(ts)
        rid = rollup_id(day, ledger_doc)
        doc = self._docs.get(rid)
        if doc is None:
            doc = {"_id": rid, "day": day, "dayTs": day_start_ms(ts), "calls": 0,
                   **{d: ledger_doc.get(d) for d in DIMENSIONS}, **{f: 0 for f in SUM_FIELDS}}
            self._docs[rid] = doc
        doc["calls"] += 1
        for f in SUM_FIELDS:
            doc[f] += ledger_doc.get(f) or 0

    def add_all(self, docs: Iterable[dict]) -> "RollupAccumulator":
        for d in docs:
            self.add(d)
        return self

    def docs(self) -> List[dict]:
        return list(self._docs.values())
