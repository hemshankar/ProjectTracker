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


class AgentSettingsUpdate(BaseModel):
    tools: Optional[Dict[str, ToolSetting]] = None
    budget: Optional[BudgetSetting] = None
    rateLimits: Optional[Dict[str, RateLimitSetting]] = None
    modelConfig: Optional[ModelConfigUpdate] = None


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
    }


def settings_to_json(doc: dict) -> dict:
    return {
        "agentId": doc["_id"],
        "tools": doc.get("tools", {t: {"enabled": False} for t in TOOL_TYPES}),
        "budget": doc.get("budget", {"capUsd": None, "unit": "usd"}),
        "rateLimits": doc.get("rateLimits") or _default_rate_limits(),
        "modelConfig": doc.get("modelConfig") or default_model_config(),
        # Ceilings for the settings UI to build its model picker and clamp
        # the maxTokens input from — the backend stays the single source
        # of truth instead of duplicating this table in the frontend.
        "modelLimits": MODEL_MAX_TOKENS,
    }
