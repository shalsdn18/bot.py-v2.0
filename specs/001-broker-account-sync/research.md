# Research: Toss Account Sync

## Decision

Use a small broker adapter layer that queries Toss Securities holdings via a dedicated client, normalizes the payload into an internal broker-position model, and reconciles it against the existing JSON-based local state before market analysis runs. This keeps the current bot flow and `positions.json` format intact while adding a clear source-of-truth boundary between broker facts and strategy state.

## Rationale

The project already stores open positions in a JSON file and executes strategy logic in `bot.py`. The safest design is additive: separate broker sync logic from the trading engine, keep `positions.json` as the default persistence format for this phase, and add reconciliation logic that only updates local state when the broker call succeeds.

The design preserves:
- `analyze_market()` behavior and existing strategy thresholds
- Telegram / Gemini / Spring webhook / daily_report integrations
- current tests and local persistence model
- minimal refactoring without a rewrite

## Alternatives considered

### 1. Embed all broker logic directly in `bot.py`

Rejected because it would increase coupling between network I/O, data normalization, and strategy execution. This would also make testing and failure handling harder in a way that conflicts with the requirement to keep the code modular and avoid a large refactor.

### 2. Convert to SQLite immediately

Rejected by explicit feature requirement. The project must keep JSON state for this phase and postpone SQLite migration to a separate State Reliability spec.

### 3. Treat API failure as an empty holdings response

Rejected because empty holdings and API failure are distinct states. A failure must not be interpreted as “zero positions,” or it would delete valid local positions.

### 4. Replace local strategy state with broker state

Rejected because the broker facts and the strategy’s internal tracking data are not equivalent. The broker position is the source of truth for actual holdings, while strategy fields such as `entry_price`, `highest_price`, `target1_hit`, and trailing state remain part of the bot's decision process.

## Decision details

- `TossClient` handles HTTP/session/token/auth concerns and isolates external API errors.
- A response normalizer converts the raw Toss holdings payload into a canonical broker position dictionary keyed by ticker.
- A reconciler compares broker positions with the existing local position map and decides whether to prune, update, add, or preserve state.
- `bot.py` calls synchronizer before `analyze_market()` so decision-making sees real holdings first.
- All API-level failures are explicitly classified as `error`, while valid empty holdings are classified as `success_no_positions`.

## Open technical choices to keep narrow

- The exact Toss endpoint and schema may vary by account or version, so the client layer will use a strict adapter contract and normalize the payload to a single internal format.
- Secret configuration will remain environment-based and never checked into source control.
- Tests will use stubbed responses and mock HTTP clients rather than real Toss API calls.
