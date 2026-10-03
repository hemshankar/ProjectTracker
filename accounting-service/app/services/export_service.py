import csv
import io
import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from .. import config
from ..models.queries import LedgerFilter
from ..repositories.ledger_repository import LedgerRepository
from .ledger_filter import build_ledger_query, validate_range
from .rows_service import public_row

CSV_COLUMNS = [
    "callId", "ts", "tsIso", "agentId", "agentName", "boardId", "boardTitle", "taskId", "taskTitle",
    "runId", "parentRunId", "callKind", "userId", "model", "inputTokens", "outputTokens",
    "cacheReadTokens", "cacheCreationTokens", "webSearchCount", "usd", "pricedByFallback",
    "latencyMs", "outcome", "anthropicRequestId", "source", "estimated", "llmCallRef",
    "schemaVersion", "ingestedAt",
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """Prefix text that a spreadsheet would run as a formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv_line(values: list) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerow(values)
    return buf.getvalue()


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ExportService:
    def __init__(self, ledger: LedgerRepository):
        self._ledger = ledger

    def prepare(self, f: LedgerFilter, fmt: str):
        """Validate eagerly (so errors become HTTP 400, not a broken stream) and return (media_type, filename, stream)."""
        validate_range(f.since_ms, f.until_ms, required=True)
        name = f"usage-{_iso(f.since_ms)[:10]}-to-{_iso(f.until_ms)[:10]}"
        if fmt == "jsonl":
            return "application/x-ndjson", f"{name}.jsonl", self._stream(f, jsonl=True)
        return "text/csv", f"{name}.csv", self._stream(f, jsonl=False)

    async def _stream(self, f: LedgerFilter, jsonl: bool) -> AsyncIterator[str]:
        if not jsonl:
            yield _csv_line(CSV_COLUMNS)
        async for chunk in self._ledger.iter_chunks(build_ledger_query(f), config.EXPORT_CHUNK_SIZE):
            yield "".join(self._line(public_row(d), jsonl) for d in chunk)

    @staticmethod
    def _line(row: dict, jsonl: bool) -> str:
        if jsonl:
            return json.dumps(row, separators=(",", ":")) + "\n"
        row = {**row, "tsIso": _iso(row["ts"])}
        return _csv_line([safe_cell(row.get(c)) if row.get(c) is not None else "" for c in CSV_COLUMNS])
