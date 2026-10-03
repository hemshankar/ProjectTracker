import pytest

from app import pricing
from app.pricing import PriceRates, cost, load_price_table

RATES = PriceRates(3.0, 15.0, 0.3, 3.75, 0.01)


def test_cost_all_terms():
    # 1M in @3 + 1M out @15 + 1M cache read @0.3 + 1M cache write @3.75 + 2 searches @0.01
    assert cost(1_000_000, 1_000_000, 1_000_000, 1_000_000, 2, RATES) == pytest.approx(22.07)


def test_cost_small_values_and_zero():
    assert cost(1000, 500, 0, 0, 0, RATES) == pytest.approx(0.0105)
    assert cost(0, 0, 0, 0, 0, RATES) == 0


def test_unknown_model_uses_fallback_flag(monkeypatch):
    monkeypatch.setattr(pricing, "_TABLE", {"known": RATES})
    assert pricing.rates_for("known") == (RATES, False)
    rates, by_fallback = pricing.rates_for("mystery")
    assert by_fallback is True
    assert rates.input_per_mtok == pricing.config.ANTHROPIC_INPUT_COST_PER_MTOK
    assert rates.output_per_mtok == pricing.config.ANTHROPIC_OUTPUT_COST_PER_MTOK


def test_overrides_merge_over_table():
    base = {"m": RATES}
    out = load_price_table(base, '{"m": {"input_per_mtok": 1}, "new": {"input_per_mtok": 2, "output_per_mtok": 4}}')
    assert out["m"].input_per_mtok == 1 and out["m"].output_per_mtok == 15.0  # partial override keeps rest
    assert out["new"] == PriceRates(2.0, 4.0)
    assert base["m"] == RATES  # base untouched


@pytest.mark.parametrize("bad", ["{nope", "[]", '{"m": {"bogus": 1}}', '{"m": {"input_per_mtok": "x"}}', '{"m": 5}'])
def test_bad_override_json_fails_loudly(bad):
    with pytest.raises(ValueError, match="PRICING_OVERRIDES_JSON"):
        load_price_table({}, bad)


def test_empty_overrides_is_noop():
    assert load_price_table({"m": RATES}, "  ") == {"m": RATES}


def test_event_rates_shape():
    assert RATES.to_event_rates() == {"input": 3.0, "output": 15.0, "cacheRead": 0.3, "cacheWrite": 3.75, "webSearch": 0.01}
