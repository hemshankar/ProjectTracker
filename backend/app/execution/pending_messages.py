"""Chat-message builders for the task loop's four suspend points — a
proposed mutating action, a clarifying question, a manual-follow-up hold,
and a peer-Agent delegation — each posted as a `pending` chat entry the
loop's caller persists, then later resolved in place (Phase 7's in-place
chat edits, never a delete).
"""
from ..models import new_id


def action_request_message(
    task_id: str, description: str, tool_name: str, params: dict, tool_use_id: str, lead_text: str
) -> dict:
    return {
        "id": new_id(),
        "role": "assistant",
        "type": "action_request",
        "text": lead_text,
        "payload": {
            "taskId": task_id,
            "description": description,
            "tool": tool_name,
            "params": params,
            "toolUseId": tool_use_id,
            "status": "pending",
        },
    }


def clarification_request_message(task_id: str, question: str, tool_use_id: str, lead_text: str) -> dict:
    return {
        "id": new_id(),
        "role": "assistant",
        "type": "clarification_request",
        "text": lead_text,
        "payload": {
            "taskId": task_id,
            "question": question,
            "toolUseId": tool_use_id,
            "status": "pending",
        },
    }


def manual_hold_message(task_id: str, note: str, tool_use_id: str, lead_text: str) -> dict:
    return {
        "id": new_id(),
        "role": "assistant",
        "type": "manual_hold",
        "text": lead_text,
        "payload": {
            "taskId": task_id,
            "note": note,
            "toolUseId": tool_use_id,
            "status": "pending",
        },
    }


def delegation_request_message(
    task_id: str, target_agent_id: str, target_agent_name: str, request: str, lead_text: str
) -> dict:
    return {
        "id": new_id(),
        "role": "assistant",
        "type": "delegation_request",
        "text": lead_text,
        "payload": {
            "taskId": task_id,
            "targetAgentId": target_agent_id,
            "targetAgentName": target_agent_name,
            "request": request,
            "status": "pending",
        },
    }
