from typing import Dict, Literal, Optional

from pydantic import BaseModel

from . import config

TOOL_TYPES = ("gmail", "calendar", "slack")
BudgetUnit = Literal["usd", "tokens"]

# Output-token ceilings per model, from the Models API (`max_tokens` field) —
# not all current models share the same cap (Haiku 4.5 is 64K, not 128K), so
# this is looked up per model rather than treated as one global constant.
MODEL_MAX_TOKENS: Dict[str, int] = {
    "claude-opus-5": 128000,
    "claude-sonnet-5": 128000,
    "claude-haiku-4-5": 64000,
}
DEFAULT_MODEL = config.ANTHROPIC_MODEL if config.ANTHROPIC_MODEL in MODEL_MAX_TOKENS else "claude-sonnet-5"

# Ceiling for the per-Agent override of a task run's tool-call round budget
# (see `config.TASK_MAX_TOOL_ROUNDS`) — generous enough for deep delegation
# chains without letting a runaway task loop indefinitely.
MAX_TOOL_ROUNDS_CEILING = 100

# Ceiling for the per-Agent override of `llm_calls` retention (Phase 8) —
# a year is generous debug-data retention without letting the collection
# grow unbounded by mistake.
LLM_CALL_RETENTION_DAYS_CEILING = 365


class ToolSetting(BaseModel):
    enabled: bool = False


class BudgetSetting(BaseModel):
    capUsd: Optional[float] = None
    unit: BudgetUnit = "usd"


class RateLimitSetting(BaseModel):
    capacityPerDay: int


class ModelConfigUpdate(BaseModel):
    model: Optional[str] = None
    maxTokens: Optional[int] = None
    webSearchEnabled: Optional[bool] = None


class ConcurrencySetting(BaseModel):
    # None means unlimited — a plain `count_documents` guard (Phase 6), not a
    # budget, so it has no per-unit distinction to track.
    maxConcurrentTasks: Optional[int] = None


class ExecutionSetting(BaseModel):
    # Optional here only so a PATCH can omit it and keep the stored value —
    # the resolved, stored setting always holds a concrete int (see
    # `settings_service._resolve_execution`), never a bare None to fall back
    # from, since there's no higher-level entity for this one to inherit.
    maxToolRounds: Optional[int] = None


class AgentSettingsUpdate(BaseModel):
    tools: Optional[Dict[str, ToolSetting]] = None
    budget: Optional[BudgetSetting] = None
    rateLimits: Optional[Dict[str, RateLimitSetting]] = None
    modelConfig: Optional[ModelConfigUpdate] = None
    concurrency: Optional[ConcurrencySetting] = None
    execution: Optional[ExecutionSetting] = None
    llmCallRetentionDays: Optional[int] = None


def _default_rate_limits() -> dict:
    return {t: {"capacityPerDay": config.DEFAULT_RATE_LIMIT_PER_DAY.get(t, 50)} for t in TOOL_TYPES}


def default_model_config() -> dict:
    return {"model": DEFAULT_MODEL, "maxTokens": MODEL_MAX_TOKENS[DEFAULT_MODEL], "webSearchEnabled": False}


def default_agent_settings(agent_id: str) -> dict:
    return {
        "_id": agent_id,
        "tools": {t: {"enabled": False} for t in TOOL_TYPES},
        "budget": {"capUsd": None, "unit": "usd"},
        "rateLimits": _default_rate_limits(),
        "modelConfig": default_model_config(),
        "concurrency": {"maxConcurrentTasks": None},
        "execution": {"maxToolRounds": config.TASK_MAX_TOOL_ROUNDS},
        "llmCallRetentionDays": config.DEFAULT_LLM_CALL_RETENTION_DAYS,
    }


def settings_to_json(doc: dict) -> dict:
    execution = doc.get("execution") or {}
    return {
        "agentId": doc["_id"],
        "tools": doc.get("tools", {t: {"enabled": False} for t in TOOL_TYPES}),
        "budget": doc.get("budget", {"capUsd": None, "unit": "usd"}),
        "rateLimits": doc.get("rateLimits") or _default_rate_limits(),
        "modelConfig": doc.get("modelConfig") or default_model_config(),
        "concurrency": doc.get("concurrency") or {"maxConcurrentTasks": None},
        "execution": {"maxToolRounds": execution.get("maxToolRounds") or config.TASK_MAX_TOOL_ROUNDS},
        "llmCallRetentionDays": doc.get("llmCallRetentionDays") or config.DEFAULT_LLM_CALL_RETENTION_DAYS,
        # Ceilings for the settings UI to build its model picker and clamp
        # the maxTokens/maxToolRounds/retention inputs from — the backend
        # stays the single source of truth instead of duplicating these in
        # the frontend.
        "modelLimits": MODEL_MAX_TOKENS,
        "maxToolRoundsCeiling": MAX_TOOL_ROUNDS_CEILING,
        "llmCallRetentionDaysCeiling": LLM_CALL_RETENTION_DAYS_CEILING,
    }
