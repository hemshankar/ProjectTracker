import asyncio
from typing import Dict, Iterable, List


class BoardEventBus:
    """In-process pub/sub fanning board/task status deltas out to WS subscribers."""

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

    def subscribe_many(self, board_ids: Iterable[str], queue: "asyncio.Queue[dict]") -> None:
        """Fans several boards into one shared queue, so a single connection
        (the per-agent WebSocket) can multiplex every board it has access to
        instead of opening one connection per board."""
        for board_id in board_ids:
            self._subscribers.setdefault(board_id, []).append(queue)

    def unsubscribe_many(self, board_ids: Iterable[str], queue: "asyncio.Queue[dict]") -> None:
        for board_id in board_ids:
            self.unsubscribe(board_id, queue)

    async def publish(self, board_id: str, event: dict) -> None:
        # A shared multi-board queue has no other way to tell which board an
        # event came from — task-only events never carry their own boardId —
        # so it's stamped on here rather than at every one of the many call
        # sites that publish task events.
        payload = {"boardId": board_id, **event}
        for queue in list(self._subscribers.get(board_id, [])):
            await queue.put(payload)


events = BoardEventBus()
