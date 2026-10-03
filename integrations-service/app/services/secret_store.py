import logging
import os
import time
from typing import Dict, List, Optional, Protocol

from cryptography.fernet import Fernet, InvalidToken

from .. import config
from ..errors import ConfigError

log = logging.getLogger("gateway.secrets")


class SecretStore(Protocol):
    def get(self, name: str) -> str: ...


class EnvSecretStore:
    def get(self, name: str) -> str:
        return getattr(config, name.upper(), "") or os.environ.get(name.upper(), "")


class StaticSecretStore:
    def __init__(self, values: Optional[dict] = None):
        self._values = values or {}

    def get(self, name: str) -> str:
        return self._values.get(name, "")


class DbSecretStore:
    """Fernet-encrypted values in `backend_credentials`. Reads are served from an
    in-memory cache that set/delete update, so a rotation applies without a restart."""

    def __init__(self, db, encryption_key: str):
        self._col = db["backend_credentials"]
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None
        self._cache: Dict[str, str] = {}
        self._meta: Dict[str, dict] = {}

    def _require_key(self) -> Fernet:
        if not self._fernet:
            raise ConfigError("SECRETS_ENCRYPTION_KEY is not set; credentials cannot be stored")
        return self._fernet

    async def load(self) -> None:
        if not self._fernet:
            return
        async for doc in self._col.find({}):
            try:
                self._cache[doc["name"]] = self._fernet.decrypt(doc["ciphertext"].encode()).decode()
                self._meta[doc["name"]] = {"updatedAt": doc.get("updatedAt"), "updatedBy": doc.get("updatedBy")}
            except InvalidToken:
                log.error("credential %s cannot be decrypted (wrong SECRETS_ENCRYPTION_KEY?)", doc.get("name"))

    def get(self, name: str) -> str:
        return self._cache.get(name, "")

    def meta(self, name: str) -> dict:
        return self._meta.get(name, {})

    async def set(self, name: str, value: str, actor: str) -> None:
        token = self._require_key().encrypt(value.encode()).decode()
        now = int(time.time() * 1000)
        await self._col.update_one({"name": name}, {"$set": {"ciphertext": token, "updatedAt": now, "updatedBy": actor}},
                                   upsert=True)
        self._cache[name] = value
        self._meta[name] = {"updatedAt": now, "updatedBy": actor}

    async def delete(self, name: str) -> None:
        await self._col.delete_one({"name": name})
        self._cache.pop(name, None)
        self._meta.pop(name, None)


class FallbackSecretStore:
    """DB value wins; env keeps working until the value is moved into the UI."""

    def __init__(self, primary: DbSecretStore, fallback: SecretStore):
        self.primary = primary
        self._fallback = fallback

    def get(self, name: str) -> str:
        return self.primary.get(name) or self._fallback.get(name)

    def source(self, name: str) -> str:
        if self.primary.get(name):
            return "db"
        return "env" if self._fallback.get(name) else "none"

    @property
    def writable(self) -> bool:
        return self.primary._fernet is not None
