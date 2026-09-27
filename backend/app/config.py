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


# --- Tool connections (Phase 5) ---
# Fernet key for encrypting tool_connections tokens at rest. In dev, derived
# deterministically from SESSION_SECRET_KEY so nothing else has to be set;
# set TOOL_ENCRYPTION_KEY explicitly in production.
TOOL_ENCRYPTION_KEY = os.environ.get("TOOL_ENCRYPTION_KEY", "")

# Gmail/Calendar reuse the Phase 1 Google OAuth app (GOOGLE_CLIENT_ID/SECRET)
# with additional scopes, on their own fixed callback URL (must be registered
# with Google separately from the login redirect URI).
GOOGLE_TOOLS_REDIRECT_URI = os.environ.get(
    "GOOGLE_TOOLS_REDIRECT_URI", "http://localhost:3000/api/tools/google/callback"
)

SLACK_CLIENT_ID = os.environ.get("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.environ.get("SLACK_CLIENT_SECRET", "")
SLACK_REDIRECT_URI = os.environ.get("SLACK_REDIRECT_URI", "http://localhost:3000/api/tools/slack/callback")

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

# How often a board's SSE stream checks for a gone-away client between real
# events — the only thing that lets an abandoned connection actually close.
SSE_POLL_SECONDS = 15

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
