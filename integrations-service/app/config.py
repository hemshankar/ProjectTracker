import os

INTERNAL_SERVICE_KEY = os.environ.get("INTERNAL_SERVICE_KEY", "")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "integrations")

# Bootstrap secrets (move into the admin UI's encrypted store in Phase 3).
COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
COMPOSIO_PROXY_API_KEY = os.environ.get("COMPOSIO_PROXY_API_KEY", "")
COMPOSIO_WEBHOOK_SECRET = os.environ.get("COMPOSIO_WEBHOOK_SECRET", "")
COMPOSIO_API_URL = os.environ.get("COMPOSIO_API_URL", "https://backend.composio.dev")

CONNECTION_STATUS_TTL_SECONDS = int(os.environ.get("CONNECTION_STATUS_TTL_SECONDS", "15"))
WEBHOOK_MAX_AGE_SECONDS = int(os.environ.get("WEBHOOK_MAX_AGE_SECONDS", "300"))

# IANA zone applied to calendar times that carry no offset.
DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "UTC")

# Admin UI bootstrap secrets (env only, never stored in the DB).
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
ADMIN_SESSION_SECRET = os.environ.get("ADMIN_SESSION_SECRET", "")
ADMIN_SESSION_TTL_SECONDS = int(os.environ.get("ADMIN_SESSION_TTL_SECONDS", str(8 * 3600)))
SECRETS_ENCRYPTION_KEY = os.environ.get("SECRETS_ENCRYPTION_KEY", "")
