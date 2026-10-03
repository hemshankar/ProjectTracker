"""A task's Description and Execution Summary: current value, versioned
edit, history, and restore. Both fields share these endpoints — `{field}` is
`description` or `summary` (see `task_fields.FIELDS`)."""
from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_board_access
from ..models_task_fields import TaskFieldRestore, TaskFieldWrite
from ..services import task_fields_service as svc
from ..task_fields import FieldSpec, get_field_spec

router = APIRouter(prefix="/api/boards", tags=["task-fields"])


def _spec(field: str) -> FieldSpec:
    spec = get_field_spec(field)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown task field")
    return spec


def _conflict(exc: svc.VersionConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": "This was changed since you opened it", "current": exc.current},
    )


@router.get("/{board_id}/tasks/{task_id}/fields/{field}")
async def get_task_field(
    board_id: str, task_id: str, field: str, _user: dict = Depends(require_board_access("viewer"))
):
    try:
        return await svc.get_field(board_id, task_id, _spec(field))
    except svc.TaskNotFound:
        raise HTTPException(status_code=404, detail="Task not found")


@router.put("/{board_id}/tasks/{task_id}/fields/{field}")
async def put_task_field(
    board_id: str, task_id: str, field: str, payload: TaskFieldWrite,
    user: dict = Depends(require_board_access("editor")),
):
    try:
        return await svc.write_field(
            board_id, task_id, _spec(field), payload.content, payload.baseVersion, "human", user["_id"]
        )
    except svc.TaskNotFound:
        raise HTTPException(status_code=404, detail="Task not found")
    except svc.VersionConflict as exc:
        raise _conflict(exc)
    except svc.FieldValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{board_id}/tasks/{task_id}/fields/{field}/history")
async def get_task_field_history(
    board_id: str, task_id: str, field: str, _user: dict = Depends(require_board_access("viewer"))
):
    spec = _spec(field)
    try:
        await svc.get_field(board_id, task_id, spec)  # 404s if the task isn't on this board
    except svc.TaskNotFound:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"revisions": await svc.list_revisions(task_id, spec)}


@router.post("/{board_id}/tasks/{task_id}/fields/{field}/restore")
async def restore_task_field(
    board_id: str, task_id: str, field: str, payload: TaskFieldRestore,
    user: dict = Depends(require_board_access("editor")),
):
    try:
        return await svc.restore_revision(
            board_id, task_id, _spec(field), payload.version, payload.baseVersion, user["_id"]
        )
    except svc.TaskNotFound:
        raise HTTPException(status_code=404, detail="Task or revision not found")
    except svc.VersionConflict as exc:
        raise _conflict(exc)
