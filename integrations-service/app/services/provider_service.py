from typing import List

from ..backends.base import Backend, ProviderConfig
from ..errors import BackendUnavailable, ProviderDisabled, UnknownProvider

PROVIDER_SEED: List[ProviderConfig] = [
    ProviderConfig("gmail", "Gmail", "composio", "gmail"),
    ProviderConfig("calendar", "Google Calendar", "composio", "googlecalendar"),
    ProviderConfig("slack", "Slack", "composio", "slack"),
]


def _to_doc(p: ProviderConfig) -> dict:
    return {"toolType": p.tool_type, "displayName": p.display_name, "backend": p.backend,
            "backendSlug": p.backend_slug, "authMode": p.auth_mode, "enabled": p.enabled}


def _from_doc(d: dict) -> ProviderConfig:
    return ProviderConfig(d["toolType"], d["displayName"], d["backend"], d["backendSlug"],
                          d.get("authMode", "managed_oauth"), d.get("enabled", True))


class ProviderService:
    """Reads the DB registry and resolves a provider to its backend."""

    def __init__(self, db, backends: dict):
        self._col = db["providers"]
        self._backends = backends

    async def seed(self, seed: List[ProviderConfig] = None) -> None:
        for p in seed or PROVIDER_SEED:
            # $setOnInsert: later admin edits are never overwritten by the code seed.
            await self._col.update_one({"toolType": p.tool_type}, {"$setOnInsert": _to_doc(p)}, upsert=True)

    async def list(self) -> List[ProviderConfig]:
        return [_from_doc(d) async for d in self._col.find({}).sort("toolType", 1)]

    async def get(self, tool_type: str, require_enabled: bool = True) -> ProviderConfig:
        doc = await self._col.find_one({"toolType": tool_type})
        if not doc:
            raise UnknownProvider(tool_type)
        provider = _from_doc(doc)
        if require_enabled and not provider.enabled:
            raise ProviderDisabled(tool_type)
        return provider

    def available_backends(self) -> List[str]:
        return list(self._backends)

    def backend_for(self, provider: ProviderConfig) -> Backend:
        backend = self._backends.get(provider.backend)
        if not backend:
            raise BackendUnavailable(f"backend '{provider.backend}' is not available")
        return backend
