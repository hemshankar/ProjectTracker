import asyncio
from typing import Optional

from .. import task_state
from ..database import boards_collection
from ..services import audit_service, chats_service
from . import agent_service, completion, concurrency, delegation, stopping
from . import context as run_context
from .dispatch import DispatchStrategy, LLMDispatchStrategy
from .enforcement import BudgetExceededError, halt_board
from .events import events


class AgentRunner:
    """Runs one board's tasks to completion.

    Before starting each new stage it re-fetches the board and checks
    `stopRequested` to decide whether to start the next one — but Stop is
    abrupt, not just "no new stages": `routers/boards.py`'s `/stop` also
    cancels every currently in-flight task via `stopping.task_registry`, so
    a task already mid-call is interrupted immediately rather than left to
    finish (see `_run_task`'s `CancelledError` handling). A task that
    proposes a mutating action, or hands work to a peer Agent, suspends
    instead of finishing its run; the board keeps its processing status
    until every task is actually resolved (see
    `completion.try_complete_board`).

    Ready tasks within one board are grouped into stages by a
    `DispatchStrategy` (Phase 6) — a stage's tasks run concurrently, then
    the board re-groups whatever's still idle for the next stage. This is
    advisory only: Phase 5's resource locks are what actually keep two
    concurrent tasks from touching the same external resource at once.
    """

    def __init__(self, board_id: str, agent_id: Optional[str], dispatch_strategy: Optional[DispatchStrategy] = None) -> None:
        self.board_id = board_id
        self.agent_id = agent_id
        self.dispatch_strategy = dispatch_strategy or LLMDispatchStrategy()

    async def run(self) -> None:
        try:
            while True:
                board = await boards_collection.find_one({"_id": self.board_id})
                if board is None:
                    return
                if board.get("status") not in ("queued", "running"):
                    # Already halted (e.g. by a budget-exceeded stop raised
                    # from within a just-finished task) — nothing more to do.
                    return
                if board.get("stopRequested"):
                    await self._halt("stopped", "user")
                    return

                idle_tasks = [t for t in board.get("tasks", []) if t.get("status") == "idle"]
                if not idle_tasks:
                    await completion.try_complete_board(self.board_id)
                    return

                if self.agent_id is not None and not await concurrency.wait_for_capacity(self.agent_id, self.board_id):
                    await self._halt("stopped", "user")
                    return

                stages, held_ids = await self.dispatch_strategy.group(idle_tasks, board.get("tasks", []))
                held_reason = "Waiting on another task to resolve"
                for held_id in held_ids:
                    await task_state.transition_task_status(
                        self.board_id, held_id, ["idle"], "idle", statusReason=held_reason
                    )
                    await events.publish(self.board_id, {"taskId": held_id, "status": "idle", "statusReason": held_reason})
                stage = stages[0] if stages else idle_tasks[:1]
                await asyncio.gather(*(self.run_task_by_id(t["id"]) for t in stage))
        except asyncio.CancelledError:
            raise
        except Exception:
            await task_state.transition_board_status(self.board_id, ["queued", "running"], "failed")
            await events.publish(self.board_id, {"boardId": self.board_id, "status": "failed"})

    async def run_task_by_id(self, task_id: str) -> None:
        """Re-fetches the board right before claiming — several of these may
        run concurrently within one stage, and each needs its own current
        view rather than a stale snapshot shared across the whole stage.
        Public: also used to run a single task standalone, outside `run()`'s
        own stage loop (see `routers/boards.py`'s `/tasks/{id}/run`) — the
        atomic claim inside `_run_task` makes that safe even if the board's
        own automatic loop is running at the same time."""
        board = await boards_collection.find_one({"_id": self.board_id})
        if board is None:
            return
        task = next((t for t in board.get("tasks", []) if t["id"] == task_id), None)
        if task is None or task.get("status") != "idle":
            return
        await self._run_task(board, task)

    async def _run_task(self, board: dict, task: dict) -> None:
        task_id = task["id"]
        run_id = await run_context.start_task_run(self.board_id, task_id, self.agent_id)
        claimed = await task_state.transition_task_status(
            self.board_id, task_id, ["idle"], "running", currentRunId=run_id, statusReason=None
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

        # Registered under the task's own id (not the board's — see
        # `execution/registry.py` for that) so a Stop action, whether
        # per-task or board-wide, can cancel exactly this coroutine. Each
        # coroutine `asyncio.gather()`s in `run()`'s stage loop is its own
        # real `asyncio.Task`, so this correctly resolves to just the one
        # driving this specific task even when siblings are running too.
        current = asyncio.current_task()
        if current is not None:
            stopping.task_registry.register(task_id, current)
        try:
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

            if status in ("awaiting_approval", "awaiting_reply", "awaiting_clarification", "manual"):
                # Suspended, not finished: leave currentRunId in place so the
                # resuming path (approve/reject, a delegated task's reply, or a
                # human resolving a manual hold) can later close out this same run.
                await task_state.transition_task_status(self.board_id, task_id, ["running"], status)
                await events.publish(self.board_id, {"taskId": task_id, "status": status})
                return

            await run_context.finish_task_run(run_id, status, error)
            after = await task_state.transition_task_status(
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

            resolved_task = next(
                (t for t in (after or {}).get("tasks", []) if t["id"] == task_id), task
            )
            await delegation.on_task_resolved(
                resolved_task, delegation.extract_result_text(board, task, status, error)
            )
        except asyncio.CancelledError:
            # Abrupt Stop: interrupted mid-call rather than left to finish.
            # `mark_stopped`'s own compare-and-swap makes this safe even if
            # the cancellation actually landed after the block above already
            # reached a true terminal status — it just no-ops in that case.
            await stopping.mark_stopped(self.board_id, task_id, run_id, self.agent_id)
        finally:
            if current is not None:
                stopping.task_registry.unregister(task_id, current)

    async def _do_work(self, board: dict, task: dict) -> str:
        chat = await chats_service.get_or_create_task_chat(board, task)
        before_count = len(chat["messages"])
        status = await agent_service.run_task_step(self.board_id, board, task, chat)
        new_messages = chat["messages"][before_count:]
        for message in new_messages:
            message["taskId"] = task["id"]
        await chats_service.append_messages(self.board_id, chat["id"], new_messages)
        for message in new_messages:
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
        chat = await chats_service.get_or_create_task_chat(board, task)
        message = chats_service.text_message("assistant", f"This task failed: {error}")
        message["taskId"] = task["id"]
        await chats_service.append_messages(self.board_id, chat["id"], [message])
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
