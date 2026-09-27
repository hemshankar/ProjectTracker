import asyncio
from typing import Optional

from .. import task_state
from ..database import boards_collection
from ..services import audit_service, chats_service
from . import agent_service, completion
from . import context as run_context
from .enforcement import BudgetExceededError, halt_board
from .events import events


class AgentRunner:
    """Runs one board's tasks to completion, one at a time.

    Before starting each new task it re-fetches the board and checks
    `stopRequested`; the current task is never interrupted mid-call — that
    flag check between tasks is the entire "graceful stop" behavior. A task
    that proposes a mutating action suspends in `awaiting_approval` instead
    of finishing its run; the board keeps its processing status until every
    task is actually resolved (see `completion.try_complete_board`).
    """

    def __init__(self, board_id: str, agent_id: Optional[str]) -> None:
        self.board_id = board_id
        self.agent_id = agent_id

    async def run(self) -> None:
        try:
            while True:
                board = await boards_collection.find_one({"_id": self.board_id})
                if board is None:
                    return
                if board.get("status") not in ("queued", "running"):
                    # Already halted (e.g. by a budget-exceeded stop raised
                    # from within the just-finished task) — nothing more to do.
                    return
                if board.get("stopRequested"):
                    await self._halt("stopped", "user")
                    return

                task = next((t for t in board.get("tasks", []) if t.get("status") == "idle"), None)
                if task is None:
                    await completion.try_complete_board(self.board_id)
                    return

                await self._run_task(board, task)
        except asyncio.CancelledError:
            raise
        except Exception:
            await task_state.transition_board_status(self.board_id, ["queued", "running"], "failed")
            await events.publish(self.board_id, {"boardId": self.board_id, "status": "failed"})

    async def _run_task(self, board: dict, task: dict) -> None:
        task_id = task["id"]
        run_id = await run_context.start_task_run(self.board_id, task_id, self.agent_id)
        claimed = await task_state.transition_task_status(
            self.board_id, task_id, ["idle"], "running", currentRunId=run_id
        )
        if claimed is None:
            await run_context.finish_task_run(run_id, "failed", "task already claimed")
            return
        await events.publish(self.board_id, {"taskId": task_id, "status": "running"})

        # `claimed` carries `currentRunId` (just set above); the pre-claim
        # `task`/`board` snapshots don't, and agent_service needs it to tag
        # spend records against this run.
        board = claimed
        task = next(t for t in claimed["tasks"] if t["id"] == task_id)

        error = None
        status = "done"
        budget_reason = None
        try:
            status = await self._do_work(board, task)
        except BudgetExceededError as exc:
            budget_reason = exc.reason
            status = "stopped"
        except Exception as exc:
            error = str(exc)
            status = "failed"
            await self._record_failure(board, task, error)

        if status == "awaiting_approval":
            # Suspended, not finished: leave currentRunId in place so the
            # approve/reject endpoint can resume and later close out this
            # same run.
            await task_state.transition_task_status(self.board_id, task_id, ["running"], status)
            await events.publish(self.board_id, {"taskId": task_id, "status": status})
            return

        await run_context.finish_task_run(run_id, status, error)
        await task_state.transition_task_status(
            self.board_id, task_id, ["running"], status, currentRunId=None, statusReason=budget_reason
        )
        await events.publish(self.board_id, {"taskId": task_id, "status": status, "statusReason": budget_reason})
        await audit_service.write_audit(
            agent_id=self.agent_id,
            board_id=self.board_id,
            task_id=task_id,
            entity_type="task",
            action="update",
            actor_type="agent",
            actor_id=None,
            before=task,
            after={**task, "status": status},
        )

        if budget_reason:
            # A board-wide cap, not a task-specific problem — halt the whole
            # board's processing, same graceful behavior as a user Stop.
            await halt_board(self.board_id, "stopped", budget_reason)

    async def _do_work(self, board: dict, task: dict) -> str:
        chat = await chats_service.get_or_create_active_chat(board)
        before_count = len(chat["messages"])
        status = await agent_service.run_task_step(self.board_id, board, task, chat)
        for message in chat["messages"][before_count:]:
            message["taskId"] = task["id"]
        await chats_service.save_chats(self.board_id, board["chats"], board["activeChatId"])
        for message in chat["messages"][before_count:]:
            await audit_service.write_audit(
                agent_id=self.agent_id,
                board_id=self.board_id,
                task_id=task["id"],
                entity_type="chat_message",
                action="create",
                actor_type="agent",
                actor_id=None,
                before=None,
                after=message,
            )
        return status

    async def _record_failure(self, board: dict, task: dict, error: str) -> None:
        """Surfaces an unhandled exception from `_do_work` as a normal chat
        message. Without this the failure only lands in the `task_runs`
        collection, which nothing in the UI reads — the task detail modal
        would otherwise show no activity at all for a run that blew up.
        """
        chat = await chats_service.get_or_create_active_chat(board)
        message = chats_service.text_message("assistant", f"This task failed: {error}")
        message["taskId"] = task["id"]
        chat["messages"].append(message)
        await chats_service.save_chats(self.board_id, board["chats"], board["activeChatId"])
        await audit_service.write_audit(
            agent_id=self.agent_id,
            board_id=self.board_id,
            task_id=task["id"],
            entity_type="chat_message",
            action="create",
            actor_type="agent",
            actor_id=None,
            before=None,
            after=message,
        )

    async def _halt(self, status: str, reason: Optional[str] = None) -> None:
        await halt_board(self.board_id, status, reason)
