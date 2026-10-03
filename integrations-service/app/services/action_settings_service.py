"""Per-action runtime settings editable from the admin UI: retry limit and backoff."""
from dataclasses import dataclass
from typing import List, Optional

from ..actions.catalog import CATALOG, get_action
from ..errors import InvalidInput
from .audit_service import AuditService

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY_MS = 500
MAX_ATTEMPTS_LIMIT = 10
MAX_DELAY_MS = 10_000


@dataclass(frozen=True)
class ActionSettings:
    action: str
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay_ms: int = DEFAULT_BASE_DELAY_MS


class ActionSettingsService:
    def __init__(self, db, audit: AuditService):
        self._col = db["action_settings"]
        self._audit = audit

    async def get(self, action: str) -> ActionSettings:
        definition = get_action(action)
        doc = await self._col.find_one({"action": action}) or {}
        # Writes are never auto-retried, whatever is stored.
        attempts = 1 if definition.mutating else doc.get("maxAttempts", DEFAULT_MAX_ATTEMPTS)
        return ActionSettings(action, attempts, doc.get("baseDelayMs", DEFAULT_BASE_DELAY_MS))

    async def list(self) -> List[dict]:
        out = []
        for a in CATALOG.values():
            s = await self.get(a.name)
            out.append({"action": a.name, "toolType": a.tool_type, "mutating": a.mutating, "description": a.description,
                        "inputSchema": a.input_schema, "maxAttempts": s.max_attempts, "baseDelayMs": s.base_delay_ms,
                        "retriesEditable": not a.mutating})
        return out

    async def update(self, action: str, actor: str, max_attempts: Optional[int] = None,
                     base_delay_ms: Optional[int] = None) -> dict:
        definition = get_action(action)
        changes = {}
        if max_attempts is not None:
            if definition.mutating:
                raise InvalidInput("Write actions are never retried automatically")
            if not 1 <= max_attempts <= MAX_ATTEMPTS_LIMIT:
                raise InvalidInput(f"maxAttempts must be between 1 and {MAX_ATTEMPTS_LIMIT}")
            changes["maxAttempts"] = max_attempts
        if base_delay_ms is not None:
            if not 0 <= base_delay_ms <= MAX_DELAY_MS:
                raise InvalidInput(f"baseDelayMs must be between 0 and {MAX_DELAY_MS}")
            changes["baseDelayMs"] = base_delay_ms
        if changes:
            await self._col.update_one({"action": action}, {"$set": changes}, upsert=True)
            await self._audit.record(actor, "action_settings_update", action, extra=changes)
        return next(r for r in await self.list() if r["action"] == action)
