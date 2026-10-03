from typing import AsyncIterator, List, Optional, Protocol


class LedgerRepository(Protocol):
    """Append-only ledger. Intentionally has no update or delete (FR-13)."""

    async def insert_many(self, docs: List[dict]) -> List[str]:
        """Insert idempotently on `_id`; return the ids actually inserted."""
        ...

    async def find(self, query: dict, limit: int = 100) -> List[dict]: ...

    async def count(self, query: dict) -> int: ...

    async def page(self, query: dict, limit: int, after: Optional[tuple] = None,
                   descending: bool = True) -> List[dict]:
        """Keyset page ordered by (ts, _id); `after` is the last (ts, _id) seen."""
        ...

    def iter_chunks(self, query: dict, chunk_size: int) -> AsyncIterator[List[dict]]:
        """Stream matching rows oldest-first in chunks, never loading all of them."""
        ...

    async def latest_by(self, field: str, ids: List[str], agent_id: str, name_field: str) -> List[dict]:
        """Newest non-null `name_field` snapshot per value of `field`, as `{_id, name}`."""
        ...

    async def stats(self, query: dict) -> dict: ...

    async def missing_ids(self, ids: List[str]) -> List[str]:
        """The subset of `ids` with no ledger row (primary-key lookups)."""
        ...
