from typing import List

from ..errors import InvalidInput
from .audit_service import AuditService
from .secret_store import FallbackSecretStore

# name -> label. Per-provider custom OAuth client credentials get added here later.
CREDENTIALS = {
    "composio_api_key": "Composio API key",
    "composio_proxy_api_key": "Composio proxy API key (Proxy execute)",
    "composio_webhook_secret": "Composio webhook secret",
}
BACKEND_CREDENTIALS = {"composio": ["composio_api_key", "composio_webhook_secret"]}


class CredentialsService:
    """Write-only: values go in, only set/unset status comes out."""

    def __init__(self, store: FallbackSecretStore, audit: AuditService):
        self._store = store
        self._audit = audit

    def list(self) -> List[dict]:
        out = []
        for name, label in CREDENTIALS.items():
            source = self._store.source(name)
            meta = self._store.primary.meta(name)
            out.append({"name": name, "label": label, "status": "set" if source != "none" else "unset",
                        "source": source, "updatedAt": meta.get("updatedAt"), "updatedBy": meta.get("updatedBy")})
        return out

    def backend_status(self, backend: str) -> str:
        names = BACKEND_CREDENTIALS.get(backend)
        if names is None:
            return "n/a"
        return "set" if all(self._store.source(n) != "none" for n in names) else "missing"

    async def set(self, name: str, value: str, actor: str) -> None:
        self._validate(name)
        if not value.strip():
            raise InvalidInput("value must not be empty")
        await self._store.primary.set(name, value.strip(), actor)
        await self._audit.record(actor, "credential.set", name)  # name only, never the value

    async def delete(self, name: str, actor: str) -> None:
        self._validate(name)
        await self._store.primary.delete(name)
        await self._audit.record(actor, "credential.delete", name)

    @staticmethod
    def _validate(name: str) -> None:
        if name not in CREDENTIALS:
            raise InvalidInput(f"unknown credential '{name}'")
