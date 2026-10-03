"""`delegate_subtask`: a nested, tool-restricted conversation the top-level
task loop can spin up to decompose part of its work (Phase 6). A sub-agent
has no identity or budget of its own — its spend posts to the same
run/task as its parent (see `agent_service.run_task_step`) — and it can't
approve its own mutating actions: if it proposes one, that bubbles up
exactly like a top-level proposal and suspends the whole task.

Each invocation gets its own `task_runs` record (`parentRunId` pointing at
the task's primary run) with a display-friendly `transcript`, so the task
detail view can show how many sub-agents worked a task and what they did —
see `services/task_activity_service.py`.
"""
import time
from typing import Any, Dict, List, Optional, Tuple

from ..chat_service import get_client
from . import context, tools, tracing
from .conversation import assistant_turn, build_task_system_prompt, split_response, tool_result_turn
from .enforcement import BudgetExceededError, check_budget

MAX_SUBAGENT_ROUNDS = 3

# Orchestration tools are for the top-level agent only — a sub-agent can't
# spawn a sub-sub-agent, and it never spends another Agent's budget itself.
_ORCHESTRATION_TOOLS = {"delegate_subtask", "delegate_to_agent", "update_task_description", "set_execution_summary"}


def _allowed_tools(names: Optional[List[str]]) -> List[tools.ToolSpec]:
    if not names:
        return [t for t in tools.TOOLS.values() if t.name not in _ORCHESTRATION_TOOLS]
    return [tools.TOOLS[n] for n in names if n in tools.TOOLS and n not in _ORCHESTRATION_TOOLS]


async def run_subtask(
    board: dict,
    task: dict,
    parent_run_id: Optional[str],
    model_config: dict,
    instructions: str,
    allowed_tool_names: Optional[List[str]],
) -> Tuple[str, Optional[dict]]:
    """Runs a scoped sub-agent conversation to completion (or until it
    proposes a mutating action). Returns `(result_text, pending_action)` —
    `pending_action` is set instead of `result_text` mattering when the
    sub-agent proposed something that needs human approval; the caller
    surfaces it exactly like a top-level `action_request`."""
    client = get_client()
    if client is None:
        return "Sub-agent unavailable — missing ANTHROPIC_API_KEY.", None

    allowed = _allowed_tools(allowed_tool_names)
    tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in allowed]
    system_prompt = (
        f"{await build_task_system_prompt(board, task)}\n\n"
        "You are a scoped sub-agent, delegated one specific piece of this task by the primary "
        f"agent working on it. Your instructions: {instructions}\n"
        "You only have access to the tools listed here, not the full set. Report back a concise "
        "result once you're done — you won't get another turn after that."
    )
    messages: List[dict] = [{"role": "user", "content": instructions or "Proceed."}]
    transcript: List[Dict[str, Any]] = [{"role": "user", "text": instructions or "Proceed."}]
    agent_id = board.get("agentId")
    board_id = board["_id"]

    sub_run_id = None
    if parent_run_id is not None:
        sub_run_id = await context.start_subagent_run(
            board_id, task["id"], agent_id, parent_run_id, instructions, allowed_tool_names
        )

    async def _finish(status: str, error: Optional[str] = None) -> None:
        if sub_run_id is not None:
            await context.finish_subagent_run(sub_run_id, status, transcript, error)

    async def _record(response: Any, tool_call: Optional[dict], latency_ms: float) -> None:
        # A sub-agent has no run of its own to bill against unless the
        # caller actually gave it one (`context.start_subagent_run` needs a
        # `parent_run_id`) — with neither, there's no task run to attribute
        # this call to, so it's skipped rather than recorded orphaned.
        if parent_run_id is None:
            return
        await tracing.record_call(
            agent_id=agent_id, board_id=board_id, task_id=task["id"],
            run_id=sub_run_id or parent_run_id, parent_run_id=parent_run_id,
            response=response, system_prompt=system_prompt, request_messages=messages,
            tool_call=tool_call, latency_ms=latency_ms,
        )

    try:
        for _ in range(MAX_SUBAGENT_ROUNDS):
            await check_budget(agent_id, board_id)
            call_started = time.monotonic()
            async with client.messages.stream(
                model=model_config["model"],
                max_tokens=model_config["maxTokens"],
                system=system_prompt,
                messages=messages,
                tools=tool_defs,
            ) as stream:
                response = await stream.get_final_message()
            latency_ms = (time.monotonic() - call_started) * 1000

            text, tool_use = split_response(response)
            if text:
                transcript.append({"role": "assistant", "text": text})

            if tool_use is None:
                await _record(response, None, latency_ms)
                await _finish("done")
                return text or "Sub-agent finished with no output.", None

            spec = tools.TOOLS.get(tool_use.name)
            if spec is not None and spec.mutating:
                description = tools.describe_action(spec, tool_use.input)
                await _record(
                    response, {"name": tool_use.name, "params": tool_use.input, "status": "awaiting_approval"},
                    latency_ms,
                )
                transcript.append({"role": "assistant", "text": f"Proposed action (awaiting approval): {description}"})
                await _finish("awaiting_approval")
                return text, {
                    "description": description,
                    "tool": tool_use.name,
                    "params": tool_use.input,
                    "toolUseId": tool_use.id,
                }

            transcript.append({"role": "tool_call", "text": f"{tool_use.name}({tool_use.input})"})
            result_text = (
                await tools.execute_tool(spec, tool_use.input, None) if spec else f"Unknown tool '{tool_use.name}'."
            )
            await _record(
                response, {"name": tool_use.name, "params": tool_use.input, "result": result_text, "status": "done"},
                latency_ms,
            )
            transcript.append({"role": "tool_result", "text": result_text})
            messages.append(assistant_turn(response, tool_use))
            messages.append(tool_result_turn(tool_use.id, result_text))

        await _finish("failed", "Sub-agent did not finish within its allotted rounds.")
        return "Sub-agent did not finish within its allotted rounds.", None
    except BudgetExceededError:
        await _finish("stopped", "budget_exceeded")
        raise
    except Exception as exc:
        await _finish("failed", str(exc))
        raise
