import asyncio
from typing import Dict, List


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

    def board_ids(self) -> List[str]:
        return list(self._tasks.keys())

    async def cancel_all(self, timeout: float = 5.0) -> None:
        """Best-effort graceful shutdown: cancels every tracked runner task and
        gives them `timeout` seconds to unwind (closing HTTP connections etc.)
        before the process exits anyway. Board/task DB status is left exactly
        as it was for `reconcile_interrupted_runs` to clean up on next
        startup — this only avoids an abrupt mid-request kill, it does not
        try to leave the board in any particular status itself.
        """
        tasks = [t for t in self._tasks.values() if not t.done()]
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.wait(tasks, timeout=timeout)


registry = RunnerRegistry()
