from typing import List

from ..database import ROLLUP_COLLECTION
from ..services.rollup_keys import SUM_FIELDS


class MongoRollupRepository:
    def __init__(self, db):
        self._col = db[ROLLUP_COLLECTION]

    async def apply(self, docs: List[dict]) -> None:
        if not docs:
            return
        for d in docs:
            inc = {"calls": d["calls"], **{f: d[f] for f in SUM_FIELDS}}
            identity = {k: v for k, v in d.items() if k != "_id" and k != "calls" and k not in SUM_FIELDS}
            await self._col.update_one({"_id": d["_id"]}, {"$setOnInsert": identity, "$inc": inc}, upsert=True)

    async def aggregate(self, pipeline: List[dict]) -> List[dict]:
        return await self._col.aggregate(pipeline).to_list(None)

    async def replace_range(self, from_ms: int, to_ms: int, docs: List[dict]) -> None:
        await self._col.delete_many({"dayTs": {"$gte": from_ms, "$lt": to_ms}})
        if docs:
            await self._col.insert_many(docs)
