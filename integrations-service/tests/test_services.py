import pytest

from app.backends.base import ProviderConfig
from app.errors import ActionFailed, NotConnected, ProviderDisabled, RateLimited, UnknownAction, UnknownProvider


async def test_seed_does_not_overwrite_admin_edits(container):
    await container.db["providers"].update_one({"toolType": "slack"}, {"$set": {"enabled": False}})
    await container.providers.seed()
    with pytest.raises(ProviderDisabled):
        await container.providers.get("slack")


async def test_unknown_provider_and_action(container):
    with pytest.raises(UnknownProvider):
        await container.providers.get("nope")
    with pytest.raises(UnknownAction):
        await container.actions.execute("a1", "slack", "slack.nope", {})


async def test_new_provider_needs_only_a_row(container, fake):
    # OCP: no router/service edit needed; a seed row + catalog/map entries are enough.
    await container.providers.seed([ProviderConfig("jira", "Jira", "composio", "jira")])
    assert "jira" in [p.tool_type for p in await container.providers.list()]


async def test_connect_flow_and_status(container):
    session = await container.connections.create_session("a1", "slack", "http://cb")
    assert "fake.example" in session.url
    statuses = {s["toolType"]: s for s in await container.connections.status_all("a1")}
    assert statuses["slack"]["connected"] and not statuses["gmail"]["connected"]
    await container.connections.disconnect("a1", "slack")
    container.connections.invalidate("a1", "slack")
    assert not (await container.connections.status("a1", "slack"))["connected"]


async def test_execute_not_connected(container):
    with pytest.raises(NotConnected):
        await container.actions.execute("a1", "slack", "slack.list_channels", {})


async def test_read_is_retried_write_is_not(container, fake):
    container.actions._sleep = _no_sleep
    await container.connections.create_session("a1", "slack", "cb")
    fake.fail_next = [RateLimited(), RateLimited()]
    assert (await container.actions.execute("a1", "slack", "slack.list_channels", {})).ok
    assert len(fake.calls) == 3

    fake.calls.clear()
    fake.fail_next = [RateLimited()]
    with pytest.raises(RateLimited):
        await container.actions.execute("a1", "slack", "slack.post_message", {"channel": "C", "text": "x"})
    assert len(fake.calls) == 1


async def test_webhook_idempotent(container):
    import json
    body = json.dumps({"id": "w1", "kind": "connected", "connection": "c1", "user": "a1", "toolkit": "slack"}).encode()
    assert await container.webhooks.handle("composio", {}, body) == "processed"
    assert await container.webhooks.handle("composio", {}, body) == "duplicate"
    doc = await container.db["connections"].find_one({"agentId": "a1", "toolType": "slack"})
    assert doc["status"] == "connected"


async def test_audit_has_no_payload(container, fake):
    await container.connections.create_session("a1", "slack", "cb")
    await container.actions.execute("a1", "slack", "slack.post_message", {"channel": "C", "text": "SECRET-BODY"})
    docs = [d async for d in container.db["audit_log"].find({})]
    assert docs and "SECRET-BODY" not in str(docs)


async def _no_sleep(_):
    return None
