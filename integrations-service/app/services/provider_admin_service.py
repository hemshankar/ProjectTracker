import logging
from typing import List, Optional

from ..errors import Conflict, GatewayError, InvalidInput
from .audit_service import AuditService
from .connection_service import ConnectionService
from .credentials_service import CredentialsService
from .provider_service import ProviderService

KNOWN_BACKENDS = ("composio", "nango", "native")
log = logging.getLogger("gateway.admin")


class ProviderAdminService:
    def __init__(self, db, providers: ProviderService, connections: ConnectionService,
                 credentials: CredentialsService, audit: AuditService):
        self._col = db["providers"]
        self._conns = db["connections"]
        self._providers = providers
        self._connections = connections
        self._credentials = credentials
        self._audit = audit

    async def _count(self, tool_type: str) -> int:
        return await self._conns.count_documents({"toolType": tool_type, "status": "connected"})

    async def list(self) -> List[dict]:
        return [await self._row(p) for p in await self._providers.list()]

    async def _row(self, p) -> dict:
        return {"toolType": p.tool_type, "displayName": p.display_name, "backend": p.backend,
                "backendSlug": p.backend_slug, "authMode": p.auth_mode, "enabled": p.enabled,
                "credentialStatus": self._credentials.backend_status(p.backend),
                "backendAvailable": p.backend in self._providers.available_backends(),
                "connectionCount": await self._count(p.tool_type)}

    async def update(self, tool_type: str, actor: str, backend: Optional[str] = None,
                     backend_slug: Optional[str] = None, enabled: Optional[bool] = None, confirm: bool = False) -> dict:
        current = await self._providers.get(tool_type, require_enabled=False)
        changes = {}
        if backend is not None and backend != current.backend:
            if backend not in KNOWN_BACKENDS:
                raise InvalidInput(f"backend must be one of {', '.join(KNOWN_BACKENDS)}")
            changes["backend"] = backend
        if backend_slug is not None and backend_slug.strip() and backend_slug != current.backend_slug:
            changes["backendSlug"] = backend_slug.strip()
        if enabled is not None and enabled != current.enabled:
            changes["enabled"] = enabled

        affected = 0
        if "backend" in changes:
            affected = await self._count(tool_type)
            if affected and not confirm:
                raise Conflict(f"Changing the backend disconnects {affected} connection(s)",
                               {"connectionsAffected": affected})
            await self._drop_connections(tool_type, current)
        if changes:
            await self._col.update_one({"toolType": tool_type}, {"$set": changes})
            self._connections.invalidate_tool(tool_type)
            old = {"backend": current.backend, "backendSlug": current.backend_slug, "enabled": current.enabled}
            for field, new in changes.items():
                await self._audit.record(actor, f"provider.{field}", tool_type,
                                         extra={"from": old[field], "to": new, "connectionsAffected": affected})
        row = await self._row(await self._providers.get(tool_type, require_enabled=False))
        return {**row, "connectionsAffected": affected}

    async def _drop_connections(self, tool_type: str, provider) -> None:
        """Tokens can't move between backends: remove them at the old one, mark ours disconnected."""
        try:
            backend = self._providers.backend_for(provider)
            async for doc in self._conns.find({"toolType": tool_type, "status": "connected"}):
                try:
                    await backend.disconnect(doc.get("backendUserId") or doc["agentId"], provider)
                except GatewayError as exc:
                    log.warning("old-backend disconnect failed for %s: %s", tool_type, exc.code)
        except GatewayError:
            pass
        await self._conns.update_many({"toolType": tool_type}, {"$set": {"status": "disconnected"}})
