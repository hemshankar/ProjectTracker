import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "scatterboard")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# --- Identity / auth (Phase 1) ---
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI", "http://localhost:3000/api/auth/google/callback"
)
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "dev-insecure-secret-change-me")
SESSION_COOKIE_NAME = "scatterboard_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", FRONTEND_ORIGIN).split(",") if o.strip()]
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"


# Per-tool rate-limit defaults (token-bucket capacity per 24h window),
# adjustable per Agent in Settings.
DEFAULT_RATE_LIMIT_PER_DAY = {
    "gmail": int(os.environ.get("RATE_LIMIT_GMAIL_PER_DAY", "50")),
    "calendar": int(os.environ.get("RATE_LIMIT_CALENDAR_PER_DAY", "50")),
    "slack": int(os.environ.get("RATE_LIMIT_SLACK_PER_DAY", "200")),
}

# Fixed cap until changed (no periodic reset) — None means unlimited.
_global_cap = os.environ.get("GLOBAL_BUDGET_CAP_USD", "")
GLOBAL_BUDGET_CAP_USD = float(_global_cap) if _global_cap else None

# Nominal $/million-token pricing used to convert LLM usage into the one
# normalized spend unit (USD) tracked in `llm_calls`.
ANTHROPIC_INPUT_COST_PER_MTOK = float(os.environ.get("ANTHROPIC_INPUT_COST_PER_MTOK", "3.0"))
ANTHROPIC_OUTPUT_COST_PER_MTOK = float(os.environ.get("ANTHROPIC_OUTPUT_COST_PER_MTOK", "15.0"))

# --- Observability (Phase 8) ---
# Default retention window for `llm_calls` (full request/response/tool-call
# detail) before a TTL index purges it — it's debug data, not the permanent
# record (that's `audit_log`). Adjustable per Agent in the Config tab.
DEFAULT_LLM_CALL_RETENTION_DAYS = int(os.environ.get("LLM_CALL_RETENTION_DAYS", "90"))

RESOURCE_LOCK_TTL_MS = 2 * 60 * 1000
RATE_LIMIT_WINDOW_MS = 24 * 60 * 60 * 1000
RATE_LIMIT_POLL_SECONDS = 2
LOCK_POLL_SECONDS = 2

# How often the per-agent board-events WebSocket re-checks the caller's
# visible board set between real events — this is what picks up a board
# that was just created, shared, or unshared without a dedicated signal
# for it.
BOARD_EVENTS_POLL_SECONDS = 15

# A task's own tool-call round budget. Each round is one model turn, and
# each `delegate_subtask`/`delegate_to_agent` dispatch consumes one round
# just like any other tool call — decomposing into N sub-agents needs N+1
# rounds minimum (the dispatches, plus one more to write the final answer),
# so this needs real headroom now that Phase 6 adds multi-step orchestration
# on top of whatever else a task's own tool use already needed.
TASK_MAX_TOOL_ROUNDS = int(os.environ.get("TASK_MAX_TOOL_ROUNDS", "12"))

HUES = ["blue", "sage", "clay", "mauve", "ochre", "slate"]

CANVAS_W = 2600
CANVAS_H = 1600
MIN_W = 220
MIN_H = 180

# --- Integrations microservice (Connections Gateway) ---
INTEGRATIONS_SERVICE_URL = os.environ.get("INTEGRATIONS_SERVICE_URL", "http://integrations:8100")
INTERNAL_SERVICE_KEY = os.environ.get("INTERNAL_SERVICE_KEY", "")

# --- Accounting microservice (usage ledger) ---
ACCOUNTING_SERVICE_URL = os.environ.get("ACCOUNTING_SERVICE_URL", "http://accounting:8200")
ACCOUNTING_SERVICE_KEY = os.environ.get("ACCOUNTING_SERVICE_KEY", "")

# JSON map merged over the per-model price table, e.g.
# {"claude-haiku-4-5": {"input_per_mtok": 1.0, "output_per_mtok": 5.0,
#                       "cache_read_per_mtok": 0.1, "cache_write_per_mtok": 1.25}}
# Invalid JSON fails startup. See pricing.py.
PRICING_OVERRIDES_JSON = os.environ.get("PRICING_OVERRIDES_JSON", "")

# --- Usage delivery (Phase 5): outbox -> accounting service, spend counters ---
OUTBOX_BATCH_SIZE = int(os.environ.get("OUTBOX_BATCH_SIZE", "100"))
OUTBOX_POLL_SECONDS = float(os.environ.get("OUTBOX_POLL_SECONDS", "2"))
OUTBOX_LEASE_SECONDS = int(os.environ.get("OUTBOX_LEASE_SECONDS", "60"))
OUTBOX_MAX_BACKOFF_SECONDS = int(os.environ.get("OUTBOX_MAX_BACKOFF_SECONDS", "300"))
OUTBOX_DELIVERED_TTL_DAYS = int(os.environ.get("OUTBOX_DELIVERED_TTL_DAYS", "7"))
USAGE_FALLBACK_PATH = os.environ.get("USAGE_FALLBACK_PATH", "/tmp/usage_fallback.jsonl")
# Cutover flag: False = check_exceeded still sums llm_calls (legacy). See phase 5 doc.
SPEND_COUNTERS_ENFORCED = os.environ.get("SPEND_COUNTERS_ENFORCED", "false").lower() in ("1", "true", "yes")

# --- Reconcile & alerts (Phase 8). Set RECONCILE_ENABLED=false to stop all background checks. ---
RECONCILE_ENABLED = os.environ.get("RECONCILE_ENABLED", "true").lower() in ("1", "true", "yes")
RECONCILE_COMPLETENESS_INTERVAL_SECONDS = int(os.environ.get("RECONCILE_COMPLETENESS_INTERVAL_SECONDS", "3600"))
RECONCILE_COUNTERS_INTERVAL_SECONDS = int(os.environ.get("RECONCILE_COUNTERS_INTERVAL_SECONDS", "3600"))
RECONCILE_WINDOW_HOURS = int(os.environ.get("RECONCILE_WINDOW_HOURS", "48"))
ALERT_OUTBOX_AGE_SECONDS = int(os.environ.get("ALERT_OUTBOX_AGE_SECONDS", "900"))
ALERT_SERVICE_DOWN_SECONDS = int(os.environ.get("ALERT_SERVICE_DOWN_SECONDS", "300"))
ALERT_FALLBACK_RATIO = float(os.environ.get("ALERT_FALLBACK_RATIO", "0.2"))
ALERT_FALLBACK_MIN_EVENTS = int(os.environ.get("ALERT_FALLBACK_MIN_EVENTS", "10"))
