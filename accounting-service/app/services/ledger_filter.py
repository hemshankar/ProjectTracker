from typing import Optional

from .. import config
from ..errors import InvalidQuery
from ..models.queries import LedgerFilter
from .rollup_keys import DAY_MS

_FIELD_MAP = (("board_id", "boardId"), ("task_id", "taskId"), ("run_id", "runId"), ("model", "model"),
              ("user_id", "userId"), ("call_kind", "callKind"), ("outcome", "outcome"))


def validate_range(since_ms: Optional[int], until_ms: Optional[int], required: bool = False) -> None:
    if required and (since_ms is None or until_ms is None):
        raise InvalidQuery("since and until are required")
    if since_ms is not None and until_ms is not None:
        if until_ms < since_ms:
            raise InvalidQuery("until must not be before since")
        if (until_ms - since_ms) > config.MAX_QUERY_RANGE_DAYS * DAY_MS:
            raise InvalidQuery(f"range exceeds {config.MAX_QUERY_RANGE_DAYS} days")


def build_ledger_query(f: LedgerFilter) -> dict:
    q: dict = {"agentId": f.agent_id}
    for attr, field in _FIELD_MAP:
        value = getattr(f, attr)
        if value:
            q[field] = value
    ts = {}
    if f.since_ms is not None:
        ts["$gte"] = f.since_ms
    if f.until_ms is not None:
        ts["$lte"] = f.until_ms
    if ts:
        q["ts"] = ts
    return q
