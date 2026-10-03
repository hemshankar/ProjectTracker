"""Composition root: the only place concrete classes are named and wired."""
from dataclasses import dataclass
from typing import Any, Optional

from . import config
from .backends.composio_backend import ComposioBackend
from .backends.composio_http import ComposioHttp
from .database import get_database
from .services.action_service import ActionService
from .services.admin_auth_service import AdminAuthService
from .services.action_settings_service import ActionSettingsService
from .services.audit_service import AuditService
from .services.connection_resolver import ConnectionResolver
from .services.connection_service import ConnectionService
from .services.credentials_service import CredentialsService
from .services.provider_admin_service import ProviderAdminService
from .services.provider_service import ProviderService
from .services.secret_store import DbSecretStore, EnvSecretStore, FallbackSecretStore
from .services.webhook_service import WebhookService


@dataclass
class Container:
    db: Any
    providers: ProviderService
    connections: ConnectionService
    actions: ActionService
    webhooks: WebhookService
    audit: AuditService
    secrets: FallbackSecretStore
    credentials: CredentialsService
    provider_admin: ProviderAdminService
    admin_auth: AdminAuthService
    action_settings: ActionSettingsService
    admin_session_ttl: int = config.ADMIN_SESSION_TTL_SECONDS


def build_container(db, backends: dict, secrets: Optional[FallbackSecretStore] = None,
                    admin_auth: Optional[AdminAuthService] = None) -> Container:
    audit = AuditService(db)
    providers = ProviderService(db, backends)
    connections = ConnectionService(db, providers, audit, config.CONNECTION_STATUS_TTL_SECONDS)
    secrets = secrets or FallbackSecretStore(DbSecretStore(db, ""), EnvSecretStore())
    credentials = CredentialsService(secrets, audit)
    action_settings = ActionSettingsService(db, audit)
    actions = ActionService(providers, audit, action_settings, ConnectionResolver(connections))
    return Container(
        db, providers, connections, actions,
        WebhookService(db, providers, connections), audit, secrets, credentials,
        ProviderAdminService(db, providers, connections, credentials, audit),
        admin_auth or AdminAuthService(config.ADMIN_PASSWORD_HASH, config.ADMIN_SESSION_SECRET,
                                       config.ADMIN_SESSION_TTL_SECONDS),
        action_settings,
    )


def build_default_container() -> Container:
    db = get_database()
    secrets = FallbackSecretStore(DbSecretStore(db, config.SECRETS_ENCRYPTION_KEY), EnvSecretStore())
    composio = ComposioBackend(ComposioHttp(secrets, config.COMPOSIO_API_URL), secrets)
    return build_container(db, {"composio": composio}, secrets=secrets)


_container = None


def get_container() -> Container:
    global _container
    if _container is None:
        _container = build_default_container()
    return _container
