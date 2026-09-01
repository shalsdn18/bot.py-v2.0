# Implementation Plan: Toss Account Sync

**Branch**: `001-broker-account-sync` | **Date**: 2026-09-01 | **Spec**: [specs/001-broker-account-sync/spec.md](specs/001-broker-account-sync/spec.md)

**Input**: Feature specification from [specs/001-broker-account-sync/spec.md](specs/001-broker-account-sync/spec.md)

## Summary

This feature adds a broker-account synchronization layer for Toss Securities while preserving the current bot design. The plan keeps the existing JSON-based strategy state, introduces a small broker adapter module, and runs the account sync before `analyze_market()` so decision logic sees actual holdings first. The design explicitly separates `broker position` (real account facts) from `strategy position` (bot-specific state) and prevents destructive behavior during API failures.

## Technical Context

**Language/Version**: Python 3.13 (project-local virtual environment)

**Primary Dependencies**: requests, yfinance, pandas, pytest, Google GenAI client

**Storage**: Existing local JSON state in `positions.json`; no SQLite migration in this phase

**Testing**: pytest with mocked broker HTTP responses and stubbed client interfaces

**Target Platform**: Local Python bot running on Windows/macOS/Linux with environment-based secrets

**Project Type**: CLI-style automation bot for market monitoring and trading decisions

**Performance Goals**: Single run sync should complete within a few seconds and avoid blocking market analysis on API timeout or authentication issues

**Constraints**: Must keep the existing runtime behavior and notification flows intact; full rewrite is forbidden; API failures must never delete local positions; external calls must be mockable in tests

**Scale/Scope**: Small single-bot repository; one market analysis loop and a few position states, not a multi-service system

## Constitution Check

*Gate status: PASS*

- The feature remains additive and does not require a full rewrite or database migration.
- The proposal preserves the existing bot’s notification and reporting integrations.
- The design uses mocked broker calls in tests, avoids hardcoded secrets, and keeps local state safe when API calls fail.
- No constitution violation is introduced because this is a modular extension, not a large-scale architectural replacement.

## Project Structure

### Documentation (this feature)

```text
specs/001-broker-account-sync/
├── plan.md              # Implementation plan
├── research.md          # Design research and decisions
├── data-model.md        # Broker and strategy data model
├── quickstart.md        # Validation guide
├── contracts/
│   └── toss-account-sync.md
├── checklists/
│   └── requirements.md
└── spec.md              # feature specification
```

### Source Code (repository root)

```text
bot.py
broker/
├── __init__.py
├── toss_client.py
├── models.py
├── reconciler.py
├── sync_service.py
config/
├── params.json
├── targets.json
positions.json
tests/
├── conftest.py
├── test_batch_download.py
├── test_bot_core.py
├── test_daily_report.py
├── test_position_state_guard.py
├── test_toss_sync.py    # new regression tests
```

**Structure Decision**: Keep the existing bot entry point and state file, but isolate Toss account logic into a small `broker/` package with a dedicated client, normalization layer, and reconciler. This follows the requirement to avoid stuffing everything into `bot.py` while keeping the rest of the system intact.

## Implementation Approach

### 1. Add broker sync modules

Add a new broker package with the following responsibilities:
- `toss_client.py`: HTTP session setup, token loading, account/holdings requests, timeout/auth/error handling
- `models.py`: canonical broker position and sync result models
- `reconciler.py`: compare local `positions.json` with normalized broker holdings
- `sync_service.py`: orchestrate fetch → normalize → reconcile → persist decision

This isolates Toss API concerns and makes the code easily stubbed in tests.

### 2. Keep JSON as the persistence format for this phase

The local file continues to store the current position map in the existing shape. The synchronization layer will merge broker data into that map, preserving pre-existing keys and strategy metadata where applicable. No SQLite migration or structural rewrite will be included in this phase.

### 3. Separate broker and strategy state

The plan maintains two separate concepts:
- `broker position`: actual account holdings, actual quantity, actual average purchase price, account-level metadata
- `strategy position`: internal trading state such as `entry_price`, `highest_price`, `target1_hit`, `trailing_active`, etc.

The reconciler merges these two views by ticker key without overwriting strategy-only fields when the broker state loads successfully.

## Detailed Design

### Toss API client structure

The Toss client should expose a single method such as `fetch_holdings()` that returns a normalized response object. The adapter will:
- load environment variables or GitHub Secrets for auth values
- build the request using the configured base URL and account selection
- classify the result as `success`, `success_no_positions`, or `error`
- provide request/response logging without leaking secrets

### Authentication and token handling

- Token, account ID, and any other secret values are read from environment variables or the host secret manager.
- No secret strings are stored in code, JSON config, or Git repositories.
- Session errors, timeout exceptions, 401/403 responses, and server-side failures are all surfaced as explicit error states.

### Holdings normalization

The external Toss response is converted into a canonical internal model with a fixed schema:
- `ticker`
- `quantity`
- `average_price`
- `market`
- `last_updated_at`
- `source = "toss"`

Normalization rules:
- Ignore unsupported or malformed entries rather than crashing the full sync
- Preserve raw broker payload for debugging only when relevant
- Standardize ticker naming to the project’s existing format (e.g., `005930.KS` or `AAPL`)

### Reconciliation algorithm

The reconciler operates by ticker and compares the normalized broker snapshot against the current local map:

1. If the broker call is `error`, return without changing the local file.
2. If the broker call is `success_no_positions`, treat it as a valid empty account and prune stale local positions only in that case.
3. For each broker-held ticker:
   - if missing locally, create a new position and mark it as `added`
   - if present locally, update quantity, average price, and account metadata
   - preserve strategy-only properties already tracked in the local map
4. For each local ticker missing from the broker data after a successful sync:
   - remove it only if the broker response was a valid successful snapshot and the ticker is not present in the account
5. Persist a sync result log with additions, removals, updates, and error details

### New buy detection

A newly discovered broker position is considered a `broker-only buy` or `manual buy` when:
- the ticker is present in the broker snapshot but absent from the local position map, or
- the quantity increased from a prior known value after the last successful sync

The reconciler will update the broker facts and retain any preexisting strategy metadata while not forcing a bot strategy buy signal. This ensures the next market analysis run sees the real account state, not a stale empty state.

### Full sell detection

A full sell is detected when:
- a ticker existed in the local map and is absent from the successful broker response, or
- the broker-reported quantity is zero for a previously tracked ticker

This should trigger a local removal or reset only in the valid success branch. A failed API call must not cause the same removal.

### Partial buy/sell and average cost changes

Partial movements are processed by comparing the previous and current quantity and average price:
- quantity increase → update broker quantity and average cost
- quantity decrease → update broker quantity and average cost
- average price change → update broker price but preserve strategy entry price unless the strategy itself later decides to rebase

The reconciler must treat these as broker facts and never overwrite the strategy entry fields unless there is an explicit strategy-driven decision.

### API failure and stale-state handling

This is a key safety rule:
- `timeout`, `401/403`, `500`, network exceptions, and other external failures are considered `error`
- `error` means: do not delete local state, do not empty the account, do not overwrite strategy position data
- only a clear successful snapshot may mutate local holdings results

This requirement prevents stale state being mistaken for a real empty account and avoids the destructive bug pattern the project explicitly rejects.

### Integration point with `bot.py`

The synchronization call should be made before `analyze_market()` in each run cycle. The call site should be narrow and explicit:
- load current local state
- run broker sync
- reconcile results
- continue with normal strategy analysis and existing integrations

This design keeps the existing market-analysis logic relatively unchanged while making the account source-of-truth explicit.

## Additional File Changes

### New files
- `broker/__init__.py`
- `broker/toss_client.py`
- `broker/models.py`
- `broker/reconciler.py`
- `broker/sync_service.py`
- `tests/test_toss_sync.py`

### Modified files
- `bot.py`: add sync invocation and safe error handling around the broker update step
- `config/params.json`: new broker-related config keys if needed for account ID, base URL, timeout thresholds
- maybe `requirements.txt` only if a library is added and not already present; otherwise no change expected

## Backward compatibility plan

The implementation will not change `positions.json` format in this phase. It will preserve all existing keys and only augment them with broker-derived fields when needed. For older files without any broker metadata, the reconciler will treat them as legacy strategy state and merge in the broker snapshot only after successful validation.

## Pytest test strategy

Add focused tests using mocked HTTP responses and stubbed client returns:

1. `test_sync_success_updates_positions_from_broker`
2. `test_sync_success_empty_holdings_does_not_fail`
3. `test_sync_failure_keeps_existing_local_positions`
4. `test_manual_buy_detected_and_reflected`
5. `test_manual_sell_detected_and_removed`
6. `test_partial_position_change_updates_quantity_and_average_cost`
7. `test_strategy_state_remains_separate_from_broker_state`
8. `test_bot_run_calls_sync_before_market_analysis`

These tests should mock the external Toss API layer instead of making real network calls, in accordance with the requirement that the feature remain testable without actual broker access.

## Implementation order

1. Create the broker adapter package and internal data model.
2. Add mockable Toss client with clear `success`/`error` classification.
3. Implement a normalization function to transform raw Toss holdings payloads into the internal model.
4. Implement the reconciliation algorithm and persistence safety checks.
5. Add integration hook into `bot.py` before `analyze_market()`.
6. Add pytest coverage for normal, empty, and failure responses.
7. Run the existing regression suite and confirm all current Telegram/Gemini/webhook and daily report behaviors still pass.

## Execution Gate

The feature is ready to proceed to implementation when:
- the adapter contract is agreed and mockable
- the `broker` package boundaries are accepted
- the reconciliation safety rules are validated against the failure/empty-account distinction
- the plan remains additive and fits within the existing bot design

## Complexity Tracking

No extra complexity justification is needed because this is a narrow feature addition with a single new integration layer and no platform-level rewrite.
