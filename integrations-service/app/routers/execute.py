from fastapi import APIRouter, Depends

from ..container import Container, get_container
from ..models import ExecuteRequest, ExecuteResponse, ProxyRequest
from ..security import require_internal_key

router = APIRouter(dependencies=[Depends(require_internal_key)])


@router.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest, c: Container = Depends(get_container)) -> ExecuteResponse:
    result = await c.actions.execute(req.agentId, req.toolType, req.action, req.args, req.caller)
    return ExecuteResponse(ok=result.ok, result=result.data, error=result.error)


@router.post("/proxy", response_model=ExecuteResponse)
async def proxy(req: ProxyRequest, c: Container = Depends(get_container)) -> ExecuteResponse:
    result = await c.actions.proxy(req.agentId, req.toolType, req.method, req.endpoint, req.params, req.body)
    return ExecuteResponse(ok=result.ok, result=result.data, error=result.error)
