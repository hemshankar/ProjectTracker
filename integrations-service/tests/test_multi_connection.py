import json

import pytest

from app.connection_migration import migrate_connections
from app.errors import Forbidden, InvalidInput, NotConnected
from app.models.connection import ConnectionRef


async def _connect(c, agent="a1", tool="gmail", owner=None, label=None):
    session = await c.connections.create_session(agent, tool, "cb", owner, label)
    await c.connections.status_all(agent, owner)  # a refresh activates it, as the UI poll does
    return session.connection_id


async def test_two_gmail_connections_are_listed_and_independent(container, fake):
    first = await _connect(container, label="work@acme.com")
    second = await _connect(container, label="me@home.com")
    gmail = [s for s in await container.connections.status_all("a1") if s["toolType"] == "gmail"]
    assert {s["connectionId"] for s in gmail} == {first, second}
    assert {s["label"] for s in gmail} == {"work@acme.com", "me@home.com"}
    assert [s["isDefault"] for s in gmail].count(True) == 1 and next(s for s in gmail if s["isDefault"])["connectionId"] == first

    await container.actions.execute("a1", "gmail", "gmail.list_messages", {}, connection_id=second)
    assert fake.calls[-1][0] == f"a1:{second}"
    await container.actions.execute("a1", "gmail", "gmail.list_messages", {})  # default
    assert fake.calls[-1][0] == f"a1:{first}"

    await container.connections.disconnect_by_id("a1", first)
    remaining = [s for s in await container.connections.status_all("a1") if s["toolType"] == "gmail"]
    assert [(s["connectionId"], s["isDefault"]) for s in remaining] == [(second, True)]  # promoted
    assert (await container.actions.execute("a1", "gmail", "gmail.list_messages", {})).ok


async def test_set_default_switches(container, fake):
    first, second = await _connect(container), await _connect(container)
    await container.connections.set_default("a1", second)
    await container.actions.execute("a1", "gmail", "gmail.list_messages", {})
    assert fake.calls[-1][0] == f"a1:{second}"
    default_ids = [s["connectionId"] for s in await container.connections.status_all("a1") if s["isDefault"]]
    assert default_ids == [second] and first not in default_ids


async def test_personal_connection_hidden_and_forbidden_for_others(container, fake):
    shared = await _connect(container)
    mine = await _connect(container, owner="u1", label="mine@x.com")
    for_owner = [s["connectionId"] for s in await container.connections.status_all("a1", "u1") if s["connectionId"]]
    for_other = [s["connectionId"] for s in await container.connections.status_all("a1", "u2") if s["connectionId"]]
    assert set(for_owner) == {shared, mine} and for_other == [shared]
    with pytest.raises(Forbidden):
        await container.actions.execute("a1", "gmail", "gmail.list_messages", {}, connection_id=mine, acting_user="u2")
    with pytest.raises(Forbidden):
        await container.actions.execute("a1", "gmail", "gmail.list_messages", {}, connection_id=mine)
    assert (await container.actions.execute("a1", "gmail", "gmail.list_messages", {},
                                            connection_id=mine, acting_user="u1")).ok
    with pytest.raises(Forbidden):
        await container.connections.disconnect_by_id("a1", mine, "u2")
    with pytest.raises(InvalidInput):
        await container.connections.set_default("a1", mine, "u1")


async def test_personal_only_resolves_for_its_owner(container, fake):
    await _connect(container, tool="slack", owner="u1")
    with pytest.raises(NotConnected):
        await container.actions.execute("a1", "slack", "slack.list_channels", {})  # nobody acting
    assert (await container.actions.execute("a1", "slack", "slack.list_channels", {}, acting_user="u1")).ok
    assert (await container.connections.status("a1", "slack", "u2"))["connected"] is False


async def test_execute_without_status_poll_refreshes_pending(container, fake):
    await container.connections.create_session("a1", "slack", "cb")
    assert (await container.actions.execute("a1", "slack", "slack.list_channels", {})).ok


async def test_unknown_connection_id_is_not_connected(container):
    with pytest.raises(NotConnected):
        await container.actions.execute("a1", "gmail", "gmail.list_messages", {}, connection_id="conn_nope")
    gmail = await _connect(container)
    with pytest.raises(NotConnected):  # right id, wrong tool
        await container.actions.execute("a1", "slack", "slack.list_channels", {}, connection_id=gmail)


async def test_legacy_backend_account_still_resolves_without_a_record(container, fake):
    fake.connections[("a1", "slack")] = "c_old"  # connected before any record existed
    assert (await container.actions.execute("a1", "slack", "slack.list_channels", {})).ok
    assert fake.calls[-1][0] == "a1"


async def test_webhook_activates_pending_record_and_makes_it_default(container, fake):
    session = await container.connections.create_session("a1", "slack", "cb")
    record = await container.connections.store.get("a1", session.connection_id)
    body = json.dumps({"id": "w9", "kind": "connected", "connection": "ca_9", "user": record.backend_user_id,
                       "toolkit": "slack"}).encode()
    assert await container.webhooks.handle("composio", {}, body) == "processed"
    stored = await container.connections.store.get("a1", session.connection_id)
    assert stored.status == "connected" and stored.is_default and stored.backend_connection_id == "ca_9"


async def test_migration_backfills_legacy_rows_and_is_idempotent(container):
    col = container.db["connections"]
    await col.insert_one({"agentId": "old", "toolType": "gmail", "status": "connected", "label": "x@y.z"})
    await migrate_connections(container.db)
    first = await col.find_one({"agentId": "old"})
    assert first["connectionId"].startswith("conn_") and first["isDefault"] is True
    assert first["backendUserId"] == "old" and first["ownerUserId"] is None and first["visibility"] == "agent"
    await migrate_connections(container.db)
    again = await col.find_one({"agentId": "old"})
    assert again["connectionId"] == first["connectionId"] and await col.count_documents({"agentId": "old"}) == 1
    status = await container.connections.status("old", "gmail")  # a migrated row needs no reconnect
    assert status["connectionId"] == first["connectionId"] and status["isDefault"]


async def test_old_unique_index_is_replaced(container):
    col = container.db["connections"]
    await col.insert_one({"agentId": "a", "toolType": "gmail", "connectionId": "c1", "isDefault": True})
    await col.insert_one({"agentId": "a", "toolType": "gmail", "connectionId": "c2", "isDefault": False})
    assert await col.count_documents({"agentId": "a"}) == 2
