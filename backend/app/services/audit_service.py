from typing import Any, Literal, Optional

from ..database import audit_log_collection
from ..models import new_id, now_ms

ActorType = Literal["human", "agent"]
AuditAction = Literal["create", "update", "delete"]


async def write_audit(
    *,
    agent_id: Optional[str],
    board_id: Optional[str],
    task_id: Optional[str] = None,
    entity_type: str,
    action: AuditAction,
    actor_type: ActorType,
    actor_id: Optional[str],
    before: Any = None,
    after: Any = None,
    undo_redo: bool = False,
) -> None:
    """Append one row to the audit log. Never updated or deleted afterward.

    `undo_redo` tags a write made by `services.undo_service` replaying a
    prior entry's snapshot — excluded from `undo_service.list_undoable` so
    the replay itself never becomes a fresh undo target, and from the
    board-scoped Activity view's default reading of "what a human just did"
    (still visible in the raw log for a full audit trail).
    """
    await audit_log_collection.insert_one(
        {
            "_id": new_id(),
            "agentId": agent_id,
            "boardId": board_id,
            "taskId": task_id,
            "entityType": entity_type,
            "action": action,
            "actorType": actor_type,
            "actorId": actor_id,
            "before": before,
            "after": after,
            "undoRedo": undo_redo,
            "ts": now_ms(),
        }
    )
