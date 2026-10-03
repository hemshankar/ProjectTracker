import pytest

from app.execution import tools
from app.integrations_client import GatewayResult, IntegrationsError


class FakeIntegrationsClient:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result or GatewayResult(ok=True), error, []

    async def execute(self, agent_id, tool_type, action, args):
        self.calls.append((agent_id, tool_type, action, args))
        if self.error:
            raise self.error
        return self.result


SEND = tools.TOOLS["send_email"]
PARAMS = {"to": "a@b.c", "subject": "s", "body": "b"}


async def test_calls_gateway_with_mapped_action():
    client = FakeIntegrationsClient()
    out = await tools.execute_tool(SEND, PARAMS, "agent1", client)
    assert client.calls == [("agent1", "gmail", "gmail.send_email", PARAMS)]
    assert "a@b.c" in out


async def test_not_connected_falls_back_to_simulated():
    client = FakeIntegrationsClient(error=IntegrationsError(409, "no", "not_connected"))
    assert (await tools.execute_tool(SEND, PARAMS, "agent1", client)) == SEND.simulate(PARAMS)


@pytest.mark.parametrize("code,status", [("rate_limited", 429), ("backend_unavailable", 503), ("action_failed", 502)])
async def test_gateway_errors_raise_tool_execution_error(code, status):
    client = FakeIntegrationsClient(error=IntegrationsError(status, "boom", code))
    with pytest.raises(tools.ToolExecutionError, match="boom"):
        await tools.execute_tool(SEND, PARAMS, "agent1", client)


async def test_unsuccessful_result_raises():
    client = FakeIntegrationsClient(result=GatewayResult(ok=False, error="channel_not_found"))
    with pytest.raises(tools.ToolExecutionError, match="channel_not_found"):
        await tools.execute_tool(SEND, PARAMS, "agent1", client)


async def test_no_agent_or_internal_tool_never_calls_gateway():
    client = FakeIntegrationsClient()
    await tools.execute_tool(SEND, PARAMS, None, client)
    await tools.execute_tool(tools.TOOLS["search_notes"], {"query": "x"}, "agent1", client)
    assert client.calls == []
