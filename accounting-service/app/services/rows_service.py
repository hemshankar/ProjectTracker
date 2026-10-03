import base64
from typing import Optional

from .. import config
from ..errors import InvalidQuery
from ..models.queries import LedgerFilter, RowsPage
from ..repositories.ledger_repository import LedgerRepository
from .ledger_filter import build_ledger_query, validate_range


def encode_cursor(ts: int, row_id: str) -> str:
    return base64.urlsafe_b64encode(f"{ts}:{row_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple:
    try:
        ts, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split(":", 1)
        return int(ts), row_id
    except Exception as exc:
        raise InvalidQuery("invalid cursor") from exc


def public_row(doc: dict) -> dict:
    out = dict(doc)
    out["callId"] = out.pop("_id")
    return out


class RowsService:
    """Ledger drill-down with keyset pagination on (ts, _id), newest first."""

    def __init__(self, ledger: LedgerRepository):
        self._ledger = ledger

    async def rows(self, f: LedgerFilter, limit: int, cursor: Optional[str]) -> RowsPage:
        if not 1 <= limit <= config.MAX_PAGE_SIZE:
            raise InvalidQuery(f"limit must be between 1 and {config.MAX_PAGE_SIZE}")
        validate_range(f.since_ms, f.until_ms)
        after = decode_cursor(cursor) if cursor else None
        docs = await self._ledger.page(build_ledger_query(f), limit + 1, after, descending=True)
        has_more = len(docs) > limit
        docs = docs[:limit]
        next_cursor = encode_cursor(docs[-1]["ts"], docs[-1]["_id"]) if has_more else None
        return RowsPage(rows=[public_row(d) for d in docs], nextCursor=next_cursor)
