# Phase 3: Pricing & Full Capture

PRD: FR-1, FR-3, FR-4. Fixes the core's cost math and enriches what each call records. Delivery to the service is Phase 5. Until then the richer data lands in `llm_calls` only.

## Technical Design

### Per-model price table

New module `backend/app/pricing.py`, next to (not inside) `models_settings.py`, which only holds token limits. Prices are **data**, not code.

```python
@dataclass(frozen=True)
class PriceRates:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float
    web_search_per_call: float = 0.0
```

- `PRICE_TABLE: dict[str, PriceRates]` keyed by model id (`claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5`, matching `MODEL_MAX_TOKENS`). **Rates are seeded from the values you confirm** (PRD open item), not guessed here.
- Overridable by env, `PRICING_OVERRIDES_JSON` (a JSON map merged over the table), so a price change needs no deploy. Invalid JSON fails startup loudly.
- `DEFAULT_PRICING_MODEL` used for unknown models. `rates_for(model) -> (PriceRates, priced_by_fallback: bool)`.
- Backward compatibility: the old `ANTHROPIC_INPUT_COST_PER_MTOK` / `ANTHROPIC_OUTPUT_COST_PER_MTOK` become the **fallback rates**'s input/output, so existing deployments with custom env values keep behaving the same for unknown models.

`usd_for_usage` in `budget_service.py` is replaced by `pricing.cost(usage, rates) -> float`, a pure function:

```
usd = input·r.input + output·r.output + cache_read·r.cache_read
      + cache_creation·r.cache_write + web_searches·r.web_search_per_call   (token terms ÷ 1e6)
```

Note on Anthropic usage semantics: `usage.input_tokens` excludes cache reads and cache creation, which are reported separately, so no subtraction is needed. Confirm against a real response in the verification step.

### Reading complete usage

`UsageSnapshot` (frozen dataclass) built by `usage_from_response(response)`:
- `model` from `response.model`. Fall back to the model the caller requested.
- `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` (default 0 if absent), `web_search_requests` from `usage.server_tool_use.web_search_requests` if present.
- `request_id` from `response._request_id` when the SDK provides it, else `None`.

### Name snapshots & attribution context

`UsageContext` (frozen dataclass), resolved once per call by `UsageContextResolver`:
`agent_id, agent_name, board_id, board_title, task_id, task_title, run_id, parent_run_id, call_kind, user_id`.

- Names come from `agents_collection` / `boards_collection` (projection only: name, title, the one task's text). One small indexed read per call. Cache per `(board_id)` for the duration of a run to avoid repeated reads in a multi-round loop (`UsageContextResolver` holds a short-lived dict, so it is not global state).
- **Triggering user:** `task_runs` records no user today. Add `startedBy` to `start_task_run` (the manual start route has the session user, automatic/queued runs pass `None` → recorded as `null`, shown as "system"). Sub-agent runs inherit the parent run's `startedBy`. Chat calls use the requesting user from the route. Dispatch (planner) uses the board starter if available, else `null`. This is best-effort attribution and is documented as such.

### The event builder

`UsageEventBuilder.build(call_id, snapshot, context, rates, usd, latency_ms, outcome) -> UsageEvent` produces the **same `UsageEvent` model** the service ingests (share the schema by copying it into `backend/app/accounting/events.py` and keeping a contract test that fails if the two drift). It carries `schemaVersion=1`, `rates` (the exact rates applied), `pricedByFallback`, and `source="live"`.

### `tracing.record_call` / `budget_service.record_llm_call` changes

- `record_call` stops computing cost inline. It builds a `UsageSnapshot`, resolves rates, computes `usd`, builds the event, and **still** inserts the `llm_calls` row (content unchanged) with new fields: `model`, `cacheReadTokens`, `cacheCreationTokens`, `webSearchCount`, `callKind`, `rates`, `pricedByFallback`, `requestId`, `userId`.
- `llm_calls._id` is used as the event's `callId`. Backfill used the same ids (Phase 1), so the live and backfilled copies of one call collapse into one ledger row.
- `_summary` (the `llmCall` WebSocket event) gains `usd`, `inputTokens`, `outputTokens`, and `model`. Totals are added in Phase 5.
- The existing `usd` semantic for caps is unchanged here, apart from now being priced per model. Cap enforcement is not touched until Phase 5.

### Module split (keeps every file ≤ 300 lines)

```
backend/app/
  pricing.py                      PriceRates, PRICE_TABLE, rates_for, cost
  accounting/
    events.py                     UsageEvent, CallKind, Outcome (mirror of service model)
    usage_snapshot.py             UsageSnapshot, usage_from_response
    context.py                    UsageContext, UsageContextResolver
    event_builder.py              UsageEventBuilder
    recorder.py                   UsageRecorder  (single entry point used by call sites)
```

`UsageRecorder.record(...)` is the one function every call site (Phases 3 and 4) uses. Phase 3 has it do: build → insert `llm_calls` → publish the WebSocket summary. Phase 5 adds the outbox and counters behind the same entry point, with no call-site change.

## Implementation Plan

- [ ] `pricing.py` with the table, env overrides, fallback behavior, and the pure `cost` function (rates seeded from your confirmed values)
- [ ] `accounting/usage_snapshot.py`, `context.py`, `events.py`, `event_builder.py`, `recorder.py`
- [ ] `task_runs.startedBy` on `start_task_run` and sub-agent runs; thread the user from the manual-start route
- [ ] Refactor `tracing.record_call` to delegate to `UsageRecorder`. Keep its signature so `agent_service.py` and `subagent.py` don't change
- [ ] Extend `record_llm_call` fields. Old rows without the new fields must still render in Traces (`observability._call_summary_json` uses `.get` defaults)
- [ ] Remove `usd_for_usage`. Update its callers and `test_budget_service.py` / `test_tracing.py`
- [ ] Add `model`/tokens/`usd` to the `llmCall` summary
- [ ] Contract test: `backend/app/accounting/events.py` stays in sync with `accounting-service/app/models/events.py`
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests

- `pricing`: each model's `cost` against hand-calculated values, including cache read/write and web-search terms. Unknown model → fallback and `pricedByFallback=True`. Bad override JSON → startup error. Env overrides take precedence.
- `usage_from_response`: missing cache fields default to 0, missing `server_tool_use`, missing `usage` (→ zeros, never raises).
- `UsageContextResolver`: snapshots board title and task text, handles a deleted board (nulls, no raise), caches per run.
- `record_call`: the row has the new fields, `callKind` is `subagent` when `parent_run_id` is set, and **a failure in the context lookup or event build does not raise** and still writes the `llm_calls` row.
- Back-compat: Traces list/detail endpoints still work on a row from before this phase.
- Contract test between the two `UsageEvent` models.

## Verification

1. Run a task with a small prompt on the default model. In Mongo, the new `llm_calls` row has `model`, token fields, `rates`, and `usd` that equals tokens × rates (hand-check one).
2. Switch the workspace model to Haiku (Config tab), run again, and confirm that the `usd` per token differs and `model` is recorded correctly.
3. Run a task that uses cached prompts or web search, and confirm that the cache and search counters are non-zero (verifies the Anthropic usage-field assumption above).
4. Open the Traces tab: old and new calls both render.
5. Set `PRICING_OVERRIDES_JSON` for one model, restart, run again, and confirm that the new rate is used and recorded in `rates`.

## Rollback

Revert the `tracing`/`budget_service` refactor. The new fields in `llm_calls` are additive and ignored by old code. `startedBy` is an additive field.

## Inputs Needed From You

- **Current per-model prices** (input, output, cache read, cache write, web search) for the models you use. I won't seed them from memory.
- Confirmation that best-effort user attribution is acceptable (`null`/"system" for automatic runs).
