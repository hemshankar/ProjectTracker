"""Mongo-backed collaborators for BackfillRunner (core database)."""
from typing import Dict, List, Optional

from ..database import agents_collection, boards_collection, db, llm_calls_collection
from .backfill import Cursor

_STATE_ID = "llm_calls_backfill"
usage_backfill_state_collection = db["usage_backfill_state"]


class MongoLlmCallSource:
    async def fetch_after(self, cursor: Optional[Cursor], limit: int,
                          since: Optional[int], until: Optional[int]) -> List[dict]:
        clauses: List[dict] = []
        if cursor:
            ts, last_id = cursor
            clauses.append({"$or": [{"ts": {"$gt": ts}}, {"ts": ts, "_id": {"$gt": last_id}}]})
        if since is not None:
            clauses.append({"ts": {"$gte": since}})
        if until is not None:
            clauses.append({"ts": {"$lte": until}})
        query = {"$and": clauses} if clauses else {}
        return await llm_calls_collection.find(query).sort([("ts", 1), ("_id", 1)]).limit(limit).to_list(limit)


class MongoCheckpointStore:
    async def load(self) -> Optional[Cursor]:
        doc = await usage_backfill_state_collection.find_one({"_id": _STATE_ID})
        return (doc["lastTs"], doc["lastId"]) if doc else None

    async def save(self, cursor: Cursor) -> None:
        await usage_backfill_state_collection.update_one(
            {"_id": _STATE_ID}, {"$set": {"lastTs": cursor[0], "lastId": cursor[1]}}, upsert=True)


class MongoNameResolver:
    """Name snapshots from agents/boards that still exist; null otherwise. Cached per run."""

    def __init__(self):
        self._agents: Dict[str, Optional[str]] = {}
        self._boards: Dict[str, Optional[dict]] = {}

    async def resolve(self, row: dict) -> dict:
        agent_name = await self._agent_name(row.get("agentId"))
        board = await self._board(row.get("boardId"))
        task_title = None
        if board:
            task = next((t for t in board.get("tasks", []) if t.get("id") == row.get("taskId")), None)
            task_title = task.get("text") if task else None
        return {"agentName": agent_name, "boardTitle": board.get("title") if board else None,
                "taskTitle": task_title}

    async def _agent_name(self, agent_id: Optional[str]) -> Optional[str]:
        if not agent_id:
            return None
        if agent_id not in self._agents:
            doc = await agents_collection.find_one({"_id": agent_id}, {"name": 1})
            self._agents[agent_id] = doc.get("name") if doc else None
        return self._agents[agent_id]

    async def _board(self, board_id: Optional[str]) -> Optional[dict]:
        if not board_id:
            return None
        if board_id not in self._boards:
            self._boards[board_id] = await boards_collection.find_one(
                {"_id": board_id}, {"title": 1, "tasks.id": 1, "tasks.text": 1})
        return self._boards[board_id]
