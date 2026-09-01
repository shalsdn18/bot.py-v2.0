# Quickstart: Toss Account Sync Validation

## Prerequisites

- Python environment configured for the repository
- Required environment variables set:
  - `TOSS_API_BASE_URL` or equivalent configurable endpoint
  - `TOSS_ACCESS_TOKEN` or equivalent secret token
  - `TOSS_ACCOUNT_ID` or equivalent account selector
  - `TELEGRAM_TOKEN` and `CHAT_ID` for existing bot features
- `config/params.json` and `config/targets.json` available

## Validation scenarios

### 1. Normal broker sync

1. Set the mock or stubbed Toss response to include a valid account snapshot with one or more holdings.
2. Run the sync entry point before `analyze_market()`.
3. Confirm the position map reflects broker holdings and retains strategy metadata where relevant.
4. Confirm no regression in Telegram/Gemini/webhook notifications.

### 2. Empty holdings response

1. Set the broker mock to return a valid success response with zero holdings.
2. Run the sync path.
3. Confirm the system treats it as a successful empty account, not as an API failure.
4. Confirm stale positions are removed only in this success case.

### 3. API failure

1. Simulate timeout, 401, or server error from the Toss client.
2. Run the sync path.
3. Confirm local `positions.json` remains unchanged.
4. Confirm logs identify the state as a failure and no destructive action is taken.

### 4. Manual position changes

1. Use a mock broker response showing a new position, partial sell, or average price change.
2. Run the sync.
3. Confirm the reconciler updates only the affected ticker and preserves strategy values that are not broker facts.

## Commands

- Run the regression suite:
  - `python -m pytest -q`

- Optional focused checks:
  - `python -m pytest tests/test_toss_sync.py -q`
  - `python -m pytest tests/test_position_state_guard.py -q`

## Expected outcomes

- Current tests continue to pass.
- Sync path behavior is validated via mocks/stubs rather than live Toss calls.
- No full rewrite or SQLite migration is required in this phase.
