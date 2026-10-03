"""Mongo-backed CallSource for the completeness check."""
from typing import List, Optional

from ...database import llm_calls_collection


class MongoCallSource:
    async def page(self, since_ms: int, after_id: Optional[str], limit: int) -> List[dict]:
        query: dict = {"ts": {"$gte": since_ms}}
        if after_id:
            query["_id"] = {"$gt": after_id}
        return await llm_calls_collection.find(query, {"ts": 1, "usd": 1}).sort("_id", 1).to_list(limit)

    async def full(self, ids: List[str]) -> List[dict]:
        return await llm_calls_collection.find({"_id": {"$in": ids}}).to_list(len(ids))
