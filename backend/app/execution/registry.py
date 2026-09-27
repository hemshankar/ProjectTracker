import asyncio
from typing import Dict


class RunnerRegistry:
    """Tracks the in-process asyncio.Task running each board's AgentRunner loop.

    Single-process assumption: fine for now, a multi-replica deployment would
    need this moved to a durable queue.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}

    def register(self, board_id: str, task: asyncio.Task) -> None:
        self._tasks[board_id] = task
        task.add_done_callback(lambda _t, bid=board_id: self._tasks.pop(bid, None))

    def is_running(self, board_id: str) -> bool:
        task = self._tasks.get(board_id)
        return task is not None and not task.done()


registry = RunnerRegistry()
