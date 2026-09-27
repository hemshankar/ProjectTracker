import asyncio
from typing import Dict, List


class BoardEventBus:
    """In-process pub/sub fanning board/task status deltas out to SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List["asyncio.Queue[dict]"]] = {}

    def subscribe(self, board_id: str) -> "asyncio.Queue[dict]":
        queue: "asyncio.Queue[dict]" = asyncio.Queue()
        self._subscribers.setdefault(board_id, []).append(queue)
        return queue

    def unsubscribe(self, board_id: str, queue: "asyncio.Queue[dict]") -> None:
        subs = self._subscribers.get(board_id)
        if not subs or queue not in subs:
            return
        subs.remove(queue)
        if not subs:
            self._subscribers.pop(board_id, None)

    async def publish(self, board_id: str, event: dict) -> None:
        for queue in list(self._subscribers.get(board_id, [])):
            await queue.put(event)


events = BoardEventBus()
