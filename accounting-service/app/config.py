import os

ACCOUNTING_SERVICE_KEY = os.environ.get("ACCOUNTING_SERVICE_KEY", "")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "scatterboard_accounting")
MAX_BATCH_SIZE = int(os.environ.get("MAX_BATCH_SIZE", "500"))
# Current and previous schema versions the service accepts (NFR-8).
SUPPORTED_SCHEMA_VERSIONS = tuple(
    int(v) for v in os.environ.get("SUPPORTED_SCHEMA_VERSIONS", "1").split(",") if v.strip()
)

# Read-side bounds.
MAX_QUERY_RANGE_DAYS = int(os.environ.get("MAX_QUERY_RANGE_DAYS", "400"))
MAX_PAGE_SIZE = int(os.environ.get("MAX_PAGE_SIZE", "500"))
EXPORT_CHUNK_SIZE = int(os.environ.get("EXPORT_CHUNK_SIZE", "1000"))

# Reconcile / operations (Phase 8).
MAX_EXISTS_IDS = int(os.environ.get("MAX_EXISTS_IDS", "1000"))
ROLLUP_VERIFY_ENABLED = os.environ.get("ROLLUP_VERIFY_ENABLED", "true").lower() in ("1", "true", "yes")
ROLLUP_VERIFY_HOUR_UTC = int(os.environ.get("ROLLUP_VERIFY_HOUR_UTC", "3"))
ROLLUP_VERIFY_LOOKBACK_DAYS = int(os.environ.get("ROLLUP_VERIFY_LOOKBACK_DAYS", "30"))
