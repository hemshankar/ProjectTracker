"""Lets an agent pick one of several connected accounts of a tool by its label (e.g. an email address)."""
from typing import Dict, Iterable, Optional

from ..integrations_client import IntegrationsClient
from .tool_spec import ToolSpec

ACCOUNT_PARAM = "account"
_ACCOUNT_SCHEMA = {
    "type": "string",
    "description": "Optional. Label of the connected account to use when several are connected "
                   "(for example the email address). Omit to use the default account.",
}


def add_account_param(tools: Dict[str, ToolSpec], connector_tools: Iterable[str]) -> None:
    """Adds the optional `account` argument to every tool that runs through a connector."""
    for name in connector_tools:
        spec = tools.get(name)
        if spec is not None and spec.tool_type:
            spec.input_schema.setdefault("properties", {})[ACCOUNT_PARAM] = _ACCOUNT_SCHEMA


async def resolve_connection_id(client: IntegrationsClient, agent_id: str, tool_type: str, account: str) -> Optional[str]:
    """Maps an account label to a connectionId among the agent's shared connections.
    Raises LookupError listing the available labels when nothing matches."""
    wanted = account.strip().lower()
    mine = [c for c in await client.list_connections(agent_id)
            if c.get("toolType") == tool_type and c.get("connected") and c.get("connectionId")]
    match = next((c for c in mine if (c.get("label") or "").lower() == wanted), None)
    if match is None:
        labels = ", ".join(c.get("label") or "unnamed" for c in mine) or "none connected"
        raise LookupError(f'No {tool_type} account labelled "{account}". Available: {labels}.')
    return match["connectionId"]
