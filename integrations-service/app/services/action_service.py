import asyncio
import logging
import random
import time
from typing import Any, Mapping, Optional

from ..actions.catalog import get_action
from ..backends.base import ActionResult
from ..errors import ActionFailed, BackendUnavailable, GatewayError, RateLimited
from .action_settings_service import ActionSettingsService
from .audit_service import AuditService
from .provider_service import ProviderService

log = logging.getLogger("gateway.actions")
_RETRYABLE = (RateLimited, BackendUnavailable)


class ActionService:
    def __init__(self, providers: ProviderService, audit: AuditService, settings: ActionSettingsService,
                 sleep=asyncio.sleep):
        self._providers = providers
        self._audit = audit
        self._settings = settings
        self._sleep = sleep

    async def execute(self, agent_id: str, tool_type: str, action: str, args: Mapping[str, Any],
                      caller: str = "monolith", meta: Optional[Mapping[str, Any]] = None) -> ActionResult:
        """meta is merged into the audit entry; never payload contents."""
        extra = {"caller": caller, **(meta or {})}
        definition = get_action(action)
        provider = await self._providers.get(tool_type)
        backend = self._providers.backend_for(provider)
        # Writes are sent exactly once; only idempotent reads are retried.
        settings = await self._settings.get(action)  # retry limit / backoff are editable in the admin UI
        attempts = 1 if definition.mutating else settings.max_attempts
        base_delay = settings.base_delay_ms / 1000
        started = time.monotonic()
        outcome = "ok"
        try:
            for attempt in range(1, attempts + 1):
                try:
                    result = await backend.execute_action(agent_id, provider, action, args)
                    outcome = "ok" if result.ok else "action_failed"
                    return result
                except _RETRYABLE:
                    if attempt == attempts:
                        raise
                    await self._sleep(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.1))
            raise ActionFailed("unreachable")  # pragma: no cover
        except GatewayError as exc:
            outcome = exc.code
            raise
        finally:
            ms = int((time.monotonic() - started) * 1000)
            log.info("caller=%s provider=%s action=%s outcome=%s ms=%d", caller, tool_type, action, outcome, ms)
            await self._audit.record(caller, action, f"{agent_id}/{tool_type}", outcome, ms, extra)

    async def proxy(self, agent_id: str, tool_type: str, method: str, endpoint: str,
                    params: Optional[Mapping[str, Any]], body: Any, caller: str = "monolith") -> ActionResult:
        provider = await self._providers.get(tool_type)
        backend = self._providers.backend_for(provider)
        outcome = "ok"
        try:
            return await backend.proxy(agent_id, provider, method, endpoint, params, body)
        except GatewayError as exc:
            outcome = exc.code
            raise
        finally:
            await self._audit.record(caller, f"proxy.{method.upper()}", f"{agent_id}/{tool_type}", outcome)
