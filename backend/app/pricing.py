"""Per-model price table. Prices are data: add or change an entry (or set
`PRICING_OVERRIDES_JSON`) rather than branching in code.

`PRICE_TABLE` ships empty on purpose: rates must come from the owner's confirmed
price list. Until a model has an entry it is priced at the fallback rates
(`ANTHROPIC_INPUT/OUTPUT_COST_PER_MTOK`, no cache or web-search charge) and
flagged `pricedByFallback`.
"""
import json
from dataclasses import dataclass, fields
from typing import Dict, Tuple

from . import config


@dataclass(frozen=True)
class PriceRates:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float = 0.0
    cache_write_per_mtok: float = 0.0
    web_search_per_call: float = 0.0

    def to_event_rates(self) -> dict:
        """Shape of `UsageEvent.rates` (ledger provenance)."""
        return {"input": self.input_per_mtok, "output": self.output_per_mtok,
                "cacheRead": self.cache_read_per_mtok, "cacheWrite": self.cache_write_per_mtok,
                "webSearch": self.web_search_per_call}


# model id -> rates, keyed like models_settings.MODEL_MAX_TOKENS.
PRICE_TABLE: Dict[str, PriceRates] = {}


def load_price_table(base: Dict[str, PriceRates], overrides_json: str) -> Dict[str, PriceRates]:
    """`base` with `overrides_json` merged over it. Raises ValueError on anything malformed."""
    table = dict(base)
    if not overrides_json.strip():
        return table
    try:
        raw = json.loads(overrides_json)
        if not isinstance(raw, dict):
            raise TypeError("must be a JSON object keyed by model id")
        allowed = {f.name for f in fields(PriceRates)}
        for model, rates in raw.items():
            if not isinstance(rates, dict) or set(rates) - allowed:
                raise TypeError(f"{model}: expected keys within {sorted(allowed)}")
            merged = {**(vars(table[model]) if model in table else {}), **rates}
            table[model] = PriceRates(**{k: float(v) for k, v in merged.items()})
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid PRICING_OVERRIDES_JSON: {exc}") from exc
    return table


def fallback_rates() -> PriceRates:
    return PriceRates(config.ANTHROPIC_INPUT_COST_PER_MTOK, config.ANTHROPIC_OUTPUT_COST_PER_MTOK)


_TABLE = load_price_table(PRICE_TABLE, config.PRICING_OVERRIDES_JSON)


def rates_for(model: str) -> Tuple[PriceRates, bool]:
    """(rates, priced_by_fallback)."""
    rates = _TABLE.get(model)
    return (rates, False) if rates is not None else (fallback_rates(), True)


def cost(input_tokens: int, output_tokens: int, cache_read_tokens: int, cache_creation_tokens: int,
         web_search_count: int, rates: PriceRates) -> float:
    """USD for one call. `input_tokens` excludes cache reads/creation (Anthropic reports them separately)."""
    return (
        input_tokens * rates.input_per_mtok
        + output_tokens * rates.output_per_mtok
        + cache_read_tokens * rates.cache_read_per_mtok
        + cache_creation_tokens * rates.cache_write_per_mtok
    ) / 1_000_000 + web_search_count * rates.web_search_per_call
