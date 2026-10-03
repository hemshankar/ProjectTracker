from typing import List, Protocol


class RollupRepository(Protocol):
    async def apply(self, docs: List[dict]) -> None:
        """Add each rollup doc's counters onto its (deterministic-id) document, creating it if needed."""
        ...

    async def aggregate(self, pipeline: List[dict]) -> List[dict]: ...

    async def replace_range(self, from_ms: int, to_ms: int, docs: List[dict]) -> None:
        """Replace every rollup day in [from_ms, to_ms) with `docs`."""
        ...
