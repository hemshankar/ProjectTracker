from fastapi import HTTPException

from ..database import agent_settings_collection
from ..models_settings import (
    MODEL_MAX_TOKENS,
    TOOL_TYPES,
    AgentSettingsUpdate,
    default_agent_settings,
    default_model_config,
    settings_to_json,
)
from . import audit_service


def _resolve_model_config(before_doc: dict, update) -> dict:
    current = before_doc.get("modelConfig") or default_model_config()
    model = update.model if update.model is not None else current.get("model")
    if model not in MODEL_MAX_TOKENS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'")
    ceiling = MODEL_MAX_TOKENS[model]
    max_tokens = update.maxTokens if update.maxTokens is not None else current.get("maxTokens", ceiling)
    if not (1 <= max_tokens <= ceiling):
        raise HTTPException(
            status_code=400, detail=f"maxTokens must be between 1 and {ceiling} for {model}"
        )
    web_search = (
        update.webSearchEnabled if update.webSearchEnabled is not None else current.get("webSearchEnabled", False)
    )
    return {"model": model, "maxTokens": max_tokens, "webSearchEnabled": web_search}


async def get_settings(agent_id: str) -> dict:
    doc = await agent_settings_collection.find_one({"_id": agent_id})
    if not doc:
        doc = default_agent_settings(agent_id)
        await agent_settings_collection.insert_one(doc)
    return settings_to_json(doc)


async def update_settings(agent_id: str, payload: AgentSettingsUpdate, actor_id: str) -> dict:
    before_doc = await agent_settings_collection.find_one({"_id": agent_id}) or default_agent_settings(agent_id)

    updates = {}
    if payload.tools is not None:
        tools = dict(before_doc.get("tools", {}))
        for tool_type, setting in payload.tools.items():
            if tool_type not in TOOL_TYPES:
                continue
            tools[tool_type] = {"enabled": setting.enabled}
        updates["tools"] = tools
    if payload.budget is not None:
        updates["budget"] = {"capUsd": payload.budget.capUsd, "unit": payload.budget.unit}
    if payload.rateLimits is not None:
        rate_limits = dict(before_doc.get("rateLimits", {}))
        for tool_type, setting in payload.rateLimits.items():
            if tool_type not in TOOL_TYPES:
                continue
            rate_limits[tool_type] = {"capacityPerDay": setting.capacityPerDay}
        updates["rateLimits"] = rate_limits
    if payload.modelConfig is not None:
        updates["modelConfig"] = _resolve_model_config(before_doc, payload.modelConfig)

    if not updates:
        return settings_to_json(before_doc)

    await agent_settings_collection.update_one({"_id": agent_id}, {"$set": updates}, upsert=True)
    after_doc = await agent_settings_collection.find_one({"_id": agent_id})

    await audit_service.write_audit(
        agent_id=agent_id,
        board_id=None,
        entity_type="agent_settings",
        action="update",
        actor_type="human",
        actor_id=actor_id,
        before=settings_to_json(before_doc),
        after=settings_to_json(after_doc),
    )
    return settings_to_json(after_doc)
