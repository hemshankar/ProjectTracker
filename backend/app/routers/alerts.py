"""System alerts for the accounting pipeline. Admin-only; they describe shared infrastructure, so every
workspace admin sees the same list."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..accounting.reconcile.alert_store import AlertStore
from ..dependencies import require_agent_admin
from ..models_usage import AlertOut, AlertSummary

router = APIRouter(prefix="/api", tags=["alerts"])
store = AlertStore()


@router.get("/agents/{agent_id}/alerts/summary", response_model=AlertSummary)
async def summary(agent_id: str, _a: dict = Depends(require_agent_admin())):
    return await store.summary()


@router.get("/agents/{agent_id}/alerts", response_model=List[AlertOut])
async def list_alerts(agent_id: str, includeResolved: bool = False, _a: dict = Depends(require_agent_admin())):
    return await store.list(include_resolved=includeResolved)


@router.post("/agents/{agent_id}/alerts/{key}/acknowledge", status_code=204)
async def acknowledge(agent_id: str, key: str, user: dict = Depends(require_agent_admin())):
    if not await store.acknowledge(key, user["_id"]):
        raise HTTPException(status_code=404, detail="No open alert with that key")
