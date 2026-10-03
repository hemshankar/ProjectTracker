from typing import AsyncIterator, List, Optional

from pymongo.errors import BulkWriteError

from ..database import LEDGER_COLLECTION

_DUPLICATE_KEY = 11000


def _after_clause(after: tuple, descending: bool) -> dict:
    ts, last_id = after
    cmp = "$lt" if descending else "$gt"
    return {"$or": [{"ts": {cmp: ts}}, {"ts": ts, "_id": {cmp: last_id}}]}


class MongoLedgerRepository:
    def __init__(self, db):
        self._col = db[LEDGER_COLLECTION]

    async def insert_many(self, docs: List[dict]) -> List[str]:
        if not docs:
            return []
        try:
            result = await self._col.insert_many(docs, ordered=False)
            return [str(i) for i in result.inserted_ids]
        except BulkWriteError as exc:
            errors = exc.details.get("writeErrors", [])
            if any(e.get("code") != _DUPLICATE_KEY for e in errors):
                raise
            failed = {e["index"] for e in errors}
            return [d["_id"] for i, d in enumerate(docs) if i not in failed]

    async def find(self, query: dict, limit: int = 100) -> List[dict]:
        return await self._col.find(query).sort("ts", 1).to_list(limit)

    async def count(self, query: dict) -> int:
        return await self._col.count_documents(query)

    async def page(self, query: dict, limit: int, after: Optional[tuple] = None,
                   descending: bool = True) -> List[dict]:
        q = {"$and": [query, _after_clause(after, descending)]} if after else query
        direction = -1 if descending else 1
        return await self._col.find(q).sort([("ts", direction), ("_id", direction)]).limit(limit).to_list(limit)

    async def iter_chunks(self, query: dict, chunk_size: int) -> AsyncIterator[List[dict]]:
        after = None
        while True:
            rows = await self.page(query, chunk_size, after, descending=False)
            if not rows:
                return
            yield rows
            after = (rows[-1]["ts"], rows[-1]["_id"])

    async def latest_by(self, field: str, ids: List[str], agent_id: str, name_field: str) -> List[dict]:
        """Newest non-null `name_field` snapshot for each value of `field`."""
        pipeline = [
            {"$match": {"agentId": agent_id, field: {"$in": ids}, name_field: {"$ne": None}}},
            {"$sort": {"ts": -1}},
            {"$group": {"_id": f"${field}", "name": {"$first": f"${name_field}"}}},
        ]
        return await self._col.aggregate(pipeline).to_list(len(ids) or 1)

    async def stats(self, query: dict) -> dict:
        pipeline = [{"$match": query},
                    {"$group": {"_id": None, "count": {"$sum": 1}, "minTs": {"$min": "$ts"},
                                "maxTs": {"$max": "$ts"}, "usd": {"$sum": "$usd"}}}]
        rows = await self._col.aggregate(pipeline).to_list(1)
        return rows[0] if rows else {"count": 0, "minTs": None, "maxTs": None, "usd": 0.0}

    async def missing_ids(self, ids: List[str]) -> List[str]:
        present = {d["_id"] async for d in self._col.find({"_id": {"$in": ids}}, {"_id": 1})}
        return [i for i in ids if i not in present]
