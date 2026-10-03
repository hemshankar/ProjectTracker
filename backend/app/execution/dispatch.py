"""Parallel-vs-sequential grouping for a board's ready tasks (Phase 6).

A `DispatchStrategy` groups this round's idle tasks into ordered stages; the
runner runs one stage's tasks concurrently, then re-groups whatever is still
idle for the next stage. This is advisory only — Phase 5's resource locks
are the actual safety net, so a wrong grouping just means one task in a
stage waits on a lock rather than running immediately, never a conflict.
"""
import json
import logging
import time
from typing import List, Optional, Protocol, Tuple

from ..accounting.attribution import DispatchAttribution
from ..accounting.events import CallKind
from ..accounting.recorder import get_recorder
from ..chat_service import get_client

log = logging.getLogger(__name__)

# One constant so the model priced in pricing.PRICE_TABLE is the model actually called.
DISPATCH_MODEL = "claude-haiku-4-5"

GroupResult = Tuple[List[List[dict]], List[str]]

_PAUSED_STATUSES = ("awaiting_clarification", "awaiting_approval", "awaiting_reply", "manual")


class DispatchStrategy(Protocol):
    async def group(self, tasks: List[dict], all_tasks: List[dict],
                    attribution: Optional[DispatchAttribution] = None) -> GroupResult:
        """Returns `(stages, held_ids)`. Each stage's tasks are safe to start
        together; `held_ids` are ready task ids this round deliberately
        leaves idle (not in any stage) because they look dependent on
        another, currently-paused task.

        `all_tasks` is the board's full task list (including `tasks` itself,
        plus anything not currently idle) — a strategy may use it to see
        which tasks are paused waiting on a human, and hold back any ready
        task it judges depends on one of those.
        """
        ...


class SequentialDispatchStrategy:
    """Every ready task is its own stage, in list order — the Phase 3
    behavior, and the fallback whenever the model call isn't available or
    doesn't return something usable."""

    async def group(self, tasks: List[dict], all_tasks: List[dict],
                    attribution: Optional[DispatchAttribution] = None) -> GroupResult:
        return [[t] for t in tasks], []


class LLMDispatchStrategy:
    """Asks the model, once per round, to group ready tasks by stated
    dependency and by whether they'd touch the same external target — and,
    when another task is currently paused waiting on a human, to hold back
    any ready task that looks like it depends on that paused one."""

    async def group(self, tasks: List[dict], all_tasks: List[dict],
                    attribution: Optional[DispatchAttribution] = None) -> GroupResult:
        if len(tasks) <= 1:
            return [[t] for t in tasks], []
        client = get_client()
        if client is None:
            return [[t] for t in tasks], []
        try:
            return await self._ask_model(client, tasks, all_tasks, attribution)
        except Exception:
            return [[t] for t in tasks], []

    async def _ask_model(self, client, tasks: List[dict], all_tasks: List[dict],
                         attribution: Optional[DispatchAttribution] = None) -> GroupResult:
        by_id = {t["id"]: t for t in tasks}
        listing = "\n".join(f'- {t["id"]}: {t.get("text", "")}' for t in tasks)
        paused = [t for t in all_tasks if t.get("status") in _PAUSED_STATUSES]
        paused_note = ""
        if paused:
            paused_listing = "\n".join(f'- {t["id"]}: "{t.get("text", "")}" ({t.get("status")})' for t in paused)
            paused_note = (
                "\n\nThese other tasks are currently paused, waiting on a human (not ready to run):\n"
                f"{paused_listing}\n\n"
                "If a ready task below looks like it depends on one of these paused tasks' output, "
                'include its id in a top-level "held" array instead of any stage — it will be '
                "reconsidered once the paused task resolves. Only hold a task you're fairly confident "
                "actually depends on a paused one; when in doubt, stage it normally."
            )
        prompt = (
            "Group these ready tasks into ordered stages. Tasks placed in the same stage will "
            "run concurrently, so only group tasks together when they're independent and don't "
            "name the same external target (e.g. the same email thread, calendar slot, or Slack "
            "channel). A task with a stated dependency on another goes in a later stage."
            f"{paused_note}\n\n"
            f"{listing}\n\n"
            'Respond with ONLY a JSON object like {"stages": [["a","b"],["c"]], "held": ["d"]}. '
            'Every ready task id must appear exactly once, in "stages" or in "held". Omit "held" '
            "or leave it empty if nothing should be held back."
        )
        started = time.monotonic()
        messages = [{"role": "user", "content": prompt}]
        async with client.messages.stream(model=DISPATCH_MODEL, max_tokens=1024, messages=messages) as stream:
            response = await stream.get_final_message()
        text = "".join(b.text for b in response.content if b.type == "text")
        await _record_dispatch(attribution, response, prompt, messages, text, (time.monotonic() - started) * 1000)
        raw = json.loads(_extract_json_object(text))
        raw_stages = raw.get("stages", [])
        held_ids = {tid for tid in raw.get("held", []) if tid in by_id}

        stages = [[by_id[tid] for tid in stage if tid in by_id and tid not in held_ids] for stage in raw_stages]
        placed = {t["id"] for stage in stages for t in stage}
        leftover = [t for t in tasks if t["id"] not in placed and t["id"] not in held_ids]
        if leftover:
            stages.append(leftover)
        return [stage for stage in stages if stage], list(held_ids)


async def _record_dispatch(attribution: Optional[DispatchAttribution], response, prompt: str, messages: list,
                           text: str, latency_ms: float) -> None:
    """Planner spend is board-level overhead (task_id None). Never raises into the planner."""
    try:
        await get_recorder().record(
            agent_id=attribution.agent_id if attribution else None,
            board_id=attribution.board_id if attribution else None,
            task_id=None, run_id=None, response=response, system_prompt="", request_messages=messages,
            tool_call=None, latency_ms=latency_ms, response_text=text, call_kind=CallKind.DISPATCH.value,
            user_id=attribution.user_id if attribution else None,
        )
    except Exception:
        log.exception("failed to record dispatch planner usage")


def _extract_json_object(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in model response")
    return text[start : end + 1]
