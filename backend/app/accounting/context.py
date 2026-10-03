import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from ..database import agents_collection, boards_collection, task_runs_collection

_TTL_SECONDS = 30.0
_MAX_ENTRIES = 512


@dataclass(frozen=True)
class UsageContext:
    """Who and what a call is attributed to, with name snapshots taken at call time."""

    agent_id: Optional[str]
    board_id: Optional[str]
    task_id: Optional[str]
    run_id: Optional[str]
    parent_run_id: Optional[str]
    call_kind: str
    agent_name: Optional[str] = None
    board_title: Optional[str] = None
    task_title: Optional[str] = None
    user_id: Optional[str] = None


class _TtlCache:
    """Small bounded cache so a multi-round run doesn't re-read names every call."""

    def __init__(self, ttl: float = _TTL_SECONDS, max_entries: int = _MAX_ENTRIES,
                 clock: Callable[[], float] = time.monotonic):
        self._ttl, self._max, self._clock = ttl, max_entries, clock
        self._data: Dict[Any, Tuple[float, Any]] = {}

    async def get(self, key: Any, loader: Callable[[], Awaitable[Any]]) -> Any:
        hit = self._data.get(key)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        value = await loader()
        if len(self._data) >= self._max:
            self._data.clear()
        self._data[key] = (self._clock(), value)
        return value


class UsageContextResolver:
    """Resolves a `UsageContext`. Lookups tolerate missing/deleted docs (fields become None)."""

    def __init__(self, cache: Optional[_TtlCache] = None):
        self._cache = cache or _TtlCache()

    async def resolve(self, *, agent_id: Optional[str], board_id: Optional[str], task_id: Optional[str],
                      run_id: Optional[str], parent_run_id: Optional[str], call_kind: str,
                      user_id: Optional[str] = None) -> UsageContext:
        board = await self._board(board_id)
        task = next((t for t in (board or {}).get("tasks", []) if t.get("id") == task_id), None)
        return UsageContext(
            agent_id=agent_id, board_id=board_id, task_id=task_id, run_id=run_id,
            parent_run_id=parent_run_id, call_kind=call_kind,
            agent_name=await self._agent_name(agent_id),
            board_title=(board or {}).get("title"),
            task_title=(task or {}).get("text"),
            user_id=user_id or await self._run_user(parent_run_id or run_id),
        )

    async def _agent_name(self, agent_id: Optional[str]) -> Optional[str]:
        if not agent_id:
            return None

        async def load():
            doc = await agents_collection.find_one({"_id": agent_id}, {"name": 1})
            return (doc or {}).get("name")
        return await self._cache.get(("agent", agent_id), load)

    async def _board(self, board_id: Optional[str]) -> Optional[dict]:
        if not board_id:
            return None

        async def load():
            return await boards_collection.find_one({"_id": board_id}, {"title": 1, "tasks.id": 1, "tasks.text": 1})
        return await self._cache.get(("board", board_id), load)

    async def _run_user(self, run_id: Optional[str]) -> Optional[str]:
        """Best-effort: the user who started the (parent) run, None for automatic runs."""
        if not run_id:
            return None

        async def load():
            doc = await task_runs_collection.find_one({"_id": run_id}, {"startedBy": 1})
            return (doc or {}).get("startedBy")
        return await self._cache.get(("run", run_id), load)
