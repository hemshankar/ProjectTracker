import pytest

from app.errors import InvalidInput, RateLimited


async def _slack(container):
    await container.connections.create_session("a1", "slack", "http://cb")
    container.connections.invalidate("a1", "slack")


async def test_defaults_and_listing_details(container):
    rows = {r["action"]: r for r in await container.action_settings.list()}
    read, write = rows["slack.list_channels"], rows["slack.post_message"]
    assert (read["maxAttempts"], read["retriesEditable"]) == (3, True)
    assert write["maxAttempts"] == 1 and not write["retriesEditable"]
    assert read["inputSchema"]["type"] == "object"


async def test_retry_limit_is_honoured(container, fake):
    await _slack(container)
    await container.action_settings.update("slack.list_channels", "admin", max_attempts=2, base_delay_ms=0)
    fake.fail_next = [RateLimited("x")] * 5
    with pytest.raises(RateLimited):
        await container.actions.execute("a1", "slack", "slack.list_channels", {})
    assert len(fake.calls) == 2


async def test_writes_cannot_be_given_retries(container):
    with pytest.raises(InvalidInput):
        await container.action_settings.update("slack.post_message", "admin", max_attempts=3)


@pytest.mark.parametrize("kw", [{"max_attempts": 0}, {"max_attempts": 99}, {"base_delay_ms": -1}, {"base_delay_ms": 10**6}])
async def test_bounds(container, kw):
    with pytest.raises(InvalidInput):
        await container.action_settings.update("slack.list_channels", "admin", **kw)


async def test_update_is_audited(container):
    await container.action_settings.update("slack.list_channels", "admin", max_attempts=4)
    e = next(e for e in await container.audit.list() if e["action"] == "action_settings_update")
    assert e["extra"] == {"maxAttempts": 4}
