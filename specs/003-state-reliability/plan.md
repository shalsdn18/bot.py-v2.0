# Implementation Plan: State Reliability

**Branch**: `003-state-reliability` | **Date**: 2026-09-09 | **Spec**: [specs/003-state-reliability/spec.md](spec.md)

**Input**: Feature specification for SQLite-backed state reliability, JSON migration, transactional Toss holdings synchronization, and backward-compatible position access.

## Summary

Add a small `sqlite3`-based state layer under `state/` and route the existing position-map contract through a compatibility adapter. SQLite becomes the primary durable store; `positions.json` remains a retained migration source and recovery artifact. Broker facts and strategy bookkeeping are stored in separate tables and combined only at the adapter boundary.

The implementation will not add Toss order creation, conditional orders, automated execution, WebSocket ingestion, PostgreSQL, or an ORM. Network fetching remains outside database transactions. A validated Toss snapshot is applied in one short SQLite write transaction, with failure-safe rollback and an append-only sync-history record.

## Technical Context

**Language/Version**: Existing project Python runtime; standard-library `sqlite3`, `json`, `pathlib`, `contextlib`, and `threading` only for the new persistence layer

**Primary Dependencies**: Existing `requests`, `pytest`, and project dependencies; no ORM or new database driver

**Storage**: SQLite file at a configurable path, defaulting to `state/bot_state.sqlite3` relative to the repository/runtime data directory; legacy `positions.json` remains untouched during migration

**Testing**: pytest with `tmp_path` SQLite files, mocked Toss client responses, and controlled concurrent worker threads/processes where practical

**Target Platform**: Local runs and GitHub Actions on Windows/macOS/Linux

**Scale/Scope**: One bot process or a small number of overlapping runs, position-sized state, short transactions, no distributed database

**ORM Decision**: Do not introduce an ORM. The current schema is small, SQLite is already available through Python's standard library, and explicit SQL makes transaction boundaries, WAL configuration, migration upserts, and failure behavior visible and testable. A repository interface keeps a future storage replacement possible without coupling `bot.py` to SQL.

## Constitution Check

*Gate status: PASS*

- The plan is additive and keeps `bot.py` changes narrow.
- Existing Toss holdings remain read-only and the official `result.items` contract is retained.
- Existing Telegram, Gemini, Spring webhook, and `daily_report.py` behavior is protected through the compatibility view and regression tests.
- No real order, WebSocket, PostgreSQL, distributed-lock, or full-rewrite requirement is introduced.
- The plan uses temporary databases for tests and retains the JSON source after migration.

## Project Structure

### Documentation

```text
specs/003-state-reliability/
├── spec.md
└── plan.md
```

### Planned source layout

```text
state/
├── __init__.py
├── database.py       # connection, schema initialization, WAL/busy_timeout policy
├── models.py         # typed internal records or TypedDicts, if useful
├── repository.py     # explicit SQL CRUD/upsert/query operations
├── service.py        # migration, combined compatibility view, transactional sync application
└── migration.py      # JSON-to-SQLite mapping and migration marker logic (may remain in service.py if small)

broker/
├── sync_service.py   # minimal integration change: fetch/normalize then call state service
└── ...

tests/
├── test_state_repository.py
├── test_state_migration.py
├── test_state_sync_service.py
└── existing regression tests unchanged unless an adapter fixture is required
```

The exact split between `service.py` and `migration.py` may be collapsed if the implementation remains small; the repository boundary must remain explicit.

## Database Location and Initialization

1. Add a configurable `BOT_STATE_DB_PATH` environment variable.
2. If unset, resolve the default path as `state/bot_state.sqlite3` relative to the existing runtime/repository data root, not the current working directory when that can vary between local and GitHub Actions execution.
3. Create the parent directory with `mkdir(parents=True, exist_ok=True)` during initialization.
4. Open a fresh connection per repository operation or per service unit of work with `check_same_thread=True` by default; do not share a connection across processes.
5. Set connection pragmas immediately after opening:

   ```sql
   PRAGMA foreign_keys = ON;
   PRAGMA busy_timeout = 5000;
   PRAGMA journal_mode = WAL;
   PRAGMA synchronous = NORMAL;
   ```

6. Read back `PRAGMA journal_mode` and expose the actual mode for diagnostics/tests. If WAL cannot be enabled, fail initialization clearly or use the documented fallback rather than silently claiming WAL.
7. Run schema creation in an idempotent initialization transaction using `CREATE TABLE IF NOT EXISTS` and indexes.
8. Do not run schema initialization or migration against a test's production path; tests pass an explicit `tmp_path / "state.sqlite3"`.

### WAL decision

Adopt WAL for the primary file. It permits readers to continue while a short writer transaction is active and is suitable for the expected local/GitHub Actions concurrency. WAL is not a substitute for transaction boundaries: writers still serialize. The plan does not copy or delete `-wal`/`-shm` files manually. A future deployment-specific restriction can use rollback journaling only if initialization reports and tests the fallback explicitly.

## Schema Design

The initial deployment has one configured Toss account. Include `account_key` in primary keys now so future multi-account support does not require a destructive redesign. `account_key` is a non-secret stable identifier such as the configured account sequence, not an access token.

### `broker_positions`

```sql
CREATE TABLE IF NOT EXISTS broker_positions (
    account_key TEXT NOT NULL,
    ticker TEXT NOT NULL,
    broker_quantity REAL NOT NULL CHECK (broker_quantity >= 0),
    broker_average_price REAL NOT NULL CHECK (broker_average_price >= 0),
    broker_market TEXT NOT NULL,
    broker_currency TEXT,
    broker_last_updated_at TEXT,
    broker_source TEXT NOT NULL,
    raw_payload_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_key, ticker),
    UNIQUE (account_key, ticker, broker_market)
);
CREATE INDEX IF NOT EXISTS idx_broker_positions_market
    ON broker_positions(account_key, broker_market, ticker);
```

The primary identity is `(account_key, ticker)`, not `(ticker, market)`. Ticker is the broker-normalized symbol and market is an attribute. The additional unique constraint documents that one account cannot hold duplicate rows for the same ticker/market; it is redundant with the primary key for the initial identity but protects future migrations that may introduce market-aware imports.

### `strategy_positions`

```sql
CREATE TABLE IF NOT EXISTS strategy_positions (
    account_key TEXT NOT NULL,
    ticker TEXT NOT NULL,
    entry_price REAL,
    highest_price REAL,
    target1_hit INTEGER NOT NULL DEFAULT 0 CHECK (target1_hit IN (0, 1)),
    trailing_active INTEGER NOT NULL DEFAULT 0 CHECK (trailing_active IN (0, 1)),
    opened_at TEXT,
    name TEXT,
    strategy_market TEXT,
    stop_loss_pct REAL,
    target1_pct REAL,
    target2_pct REAL,
    extra_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_key, ticker)
);
CREATE INDEX IF NOT EXISTS idx_strategy_positions_market
    ON strategy_positions(account_key, strategy_market, ticker);
```

Known strategy fields are first-class columns. Existing strategy-only keys not yet modeled are stored in `extra_json` so migration and compatibility reads do not silently discard state. `entry_price` is never populated from `broker_average_price` by sync or migration unless a future explicit strategy operation writes it.

### `sync_history`

```sql
CREATE TABLE IF NOT EXISTS sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_key TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'success', 'success_no_positions', 'error')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    changed_count INTEGER NOT NULL DEFAULT 0 CHECK (changed_count >= 0),
    error_code TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_history_account_started
    ON sync_history(account_key, started_at DESC);
```

History is append-oriented. The preferred transaction behavior is to insert a completed success row in the same transaction as the snapshot. For an API failure, no position mutation occurs; record a failure row in a separate short transaction after the failed fetch, because the error is known before any snapshot write and must remain observable even though the snapshot transaction is not opened. If failure-history persistence itself fails, return the original safe error and never mutate positions.

### Foreign-key decision

Do not add a mandatory `accounts` table in this feature. The current runtime has one configured account and adding an account lifecycle table would expand scope without improving position safety. Therefore `broker_positions`, `strategy_positions`, and `sync_history` use `account_key` as a stable value but do not foreign-key it. Enable `PRAGMA foreign_keys=ON` now so future tables can safely add relationships. A future `accounts` table may add foreign keys through a planned schema migration.

### Future extension points

Keep `account_key`, `ticker`, timestamps, and source conventions consistent so future tables can use:

- `orders`: order identity, account, ticker, side, quantity, status, broker order ID, timestamps
- `executions`: fill identity, order reference, fill quantity/price, event time
- `websocket_events`: broker event ID, event type, raw payload, received time, processing status

These tables are not created in this feature, and no order/event behavior is implemented.

## Repository and Service Boundaries

### `state/database.py`

- Resolve database path.
- Open/configure connections.
- Apply pragmas and verify WAL mode.
- Initialize schema.
- Provide a context manager for commit/rollback and guaranteed close.

### `state/repository.py`

Use explicit SQL methods, with no bot-specific policy:

- `get_broker_positions(account_key)`
- `get_strategy_positions(account_key)`
- `get_combined_positions(account_key)`
- `upsert_broker_position(...)`
- `delete_broker_position(account_key, ticker)`
- `upsert_strategy_position(...)`
- `delete_strategy_position(account_key, ticker)` where the existing stale-state policy requires it
- `insert_sync_history(...)`
- `get_latest_sync_history(...)`
- `get_migration_marker(...)` / `set_migration_marker(...)`

Repository methods accept an optional active connection so the service can compose several writes inside one transaction without opening nested commits.

### `state/service.py`

Own state policy and orchestration:

- `load_positions()` returns the compatibility position map.
- `save_positions()` splits a compatibility map into broker and strategy fields and persists it transactionally.
- `migrate_positions_json()` performs idempotent JSON import.
- `apply_holdings_snapshot()` validates a normalized successful snapshot and applies it atomically.
- `record_sync_failure()` records a non-mutating failure history row.
- `ensure_migrated()` checks the migration marker and invokes migration only when required.

### Compatibility adapter rules

The adapter combines rows by `(account_key, ticker)` and returns the current callers' map shape:

- strategy keys (`entry_price`, `highest_price`, `target1_hit`, `trailing_active`, `opened_at`, `name`, risk fields) come only from `strategy_positions`;
- broker keys (`broker_quantity`, `broker_average_price`, `broker_market`, `broker_currency`, `broker_last_updated_at`, `broker_source`) come only from `broker_positions`;
- the existing `market` field may be populated from strategy market first and broker market as a compatibility fallback, but it must not replace `broker_market`;
- broker average price is never returned as `entry_price`;
- unknown strategy fields are decoded from `extra_json` and merged without allowing broker keys to overwrite them.

## Transaction Boundary and Toss Sync Flow

The network request must happen before the state write transaction.

### Successful snapshot

1. `broker.sync_service` calls the existing Toss client and normalizes the official `result.items` response.
2. If normalized status is `success` or `success_no_positions`, validate all items before opening the write transaction.
3. Open one connection and `BEGIN IMMEDIATE` to serialize writers at the start of the mutation phase.
4. Compare the full snapshot with current broker rows for the configured account.
5. Upsert every item with the exact broker fields; do not touch strategy columns.
6. Delete broker rows absent from the successful full snapshot, including all rows for a valid empty snapshot. Do not delete strategy rows solely because broker holdings are absent unless the existing compatibility policy explicitly requires it; preserve strategy history so strategy state is not lost.
7. Insert a completed `success` or `success_no_positions` `sync_history` row in the same transaction.
8. Commit. On any exception, rollback all broker/history writes and return the prior combined state.

`changed_count` is the number of broker ticker rows inserted, updated, or deleted by the snapshot. Empty-to-empty is zero; an empty snapshot that removes three broker rows is three.

### API failure

1. Fetch and classify the Toss response outside a state mutation transaction.
2. For 401, 403, 429, 500, timeout, network, malformed JSON, unsupported status, or normalization failure, do not call snapshot-apply methods.
3. Read the current combined state for the caller and optionally insert an `error` history row in its own short transaction.
4. Return `status=error` and the unchanged state. Never synthesize an empty snapshot.

### Rollback behavior

Use `with connection:` or an explicit `BEGIN IMMEDIATE`/`commit`/`rollback` wrapper. Tests must inject a repository failure after at least one broker upsert and before history completion, then verify that both the upsert and history row are absent and the original rows are byte/value equivalent.

## Migration Algorithm

### Input and mapping

1. Resolve the configured JSON path, defaulting to the existing `positions.json` location.
2. Parse the root map and validate that each key is a ticker and each value is an object.
3. Split fields by explicit allowlists:
   - strategy: `name`, `entry_price`, `highest_price`, `opened_at`, `market`, `target1_hit`, `trailing_active`, `stop_loss_pct`, `target1_pct`, `target2_pct` plus unknown strategy keys into `extra_json`;
   - broker: `broker_quantity`, `broker_average_price`, `broker_market`, `broker_currency`, `broker_last_updated_at`, `broker_source`.
4. Do not infer `broker_average_price` from `entry_price`, and do not infer `entry_price` from `broker_average_price`.
5. For legacy broker metadata stored under non-prefixed `quantity`/`average_price`, map it only when the record is explicitly identified as broker data by the existing adapter contract; otherwise preserve those values in `extra_json` rather than silently assigning them to strategy fields.
6. Upsert both domains using `(account_key, ticker)` inside one migration transaction.

### Migration completion marker

Add an internal metadata table:

```sql
CREATE TABLE IF NOT EXISTS state_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

After all rows commit, write `migration.positions_json.v1` with the source path, source file size, source modification time, and a SHA-256 digest of the source bytes. The marker is evidence of a completed migration, not a reason to trust a changed file blindly.

### Re-run and overwrite policy

- If the marker digest and source path still match, skip migration.
- If the JSON changed, do not automatically overwrite current SQLite strategy state. Require an explicit migration mode/flag for a changed source, and default to a safe no-op with a diagnostic message.
- On an explicit retry, use deterministic upserts that preserve existing strategy values unless the migration is operating on an empty/unmigrated ticker. Never replace a non-null `entry_price`, `highest_price`, or target/trailing state with defaults.
- A migration transaction includes all imported rows and the completion marker. Interruption rolls back and leaves the marker absent or unchanged.
- Never delete, rename, truncate, or rewrite `positions.json` after success.

## Existing Field Separation and Reconciliation

### Broker-only position

When a successful broker snapshot contains a ticker absent from strategy state:

- create/update `broker_positions`;
- do not create an artificial `strategy_positions` row unless the compatibility adapter requires a placeholder, and if a placeholder is unavoidable keep all strategy fields null/default and mark it as broker-only in `extra_json`;
- expose the broker facts to existing read-only strategy/reporting callers through the combined view.

### Ticker absent from broker snapshot

When a full successful snapshot omits a ticker:

- delete the stale `broker_positions` row for that account;
- preserve `strategy_positions` unless existing strategy lifecycle code explicitly removes it after observing the broker result;
- return the omission in sync result/history counts;
- never perform this deletion on API failure.

### Partial changes

For a present ticker, update broker quantity, average price, market, currency, timestamp, and source as one row. Preserve every strategy value. Quantity changes and average-cost changes are broker facts, not strategy entry rebases.

## Integration Points

### `broker/sync_service.py`

Replace the current JSON-map mutation/persistence step with:

1. load combined state from the state service for safe fallback;
2. call the existing `TossClient.fetch_holdings()`;
3. normalize/classify the response using the existing official contract;
4. on success, call `state_service.apply_holdings_snapshot()`;
5. on failure, call `record_sync_failure()` without changing positions;
6. return the existing `SyncResult` and compatibility position map shape.

The service must not fetch network data while holding a SQLite transaction.

### `bot.py`

Keep the existing `synchronize_broker_positions()` call before market analysis. Change only the state load/save source or adapter construction required to read SQLite. Preserve the existing error fallback and downstream position-map consumers. Do not move Telegram, Gemini, Spring, or daily-report logic.

### `daily_report.py`

Prefer changing only its `load_positions()` binding or injecting the same compatibility state service. Its output contract and formatting remain unchanged.

### Configuration

Add only the minimal state-path and optional tuning configuration:

- `BOT_STATE_DB_PATH`
- `BOT_STATE_ACCOUNT_KEY` or reuse the configured Toss account sequence without storing secrets
- optional `BOT_STATE_BUSY_TIMEOUT_MS`, default `5000`

Do not add credentials to JSON config or source.

## Test Strategy

All new database tests use `tmp_path` and a fresh database path. Fixtures must not point to repository `positions.json` or any production database.

### Repository and schema tests

- initialization creates tables and indexes idempotently;
- WAL mode is enabled and read back, or the documented fallback is surfaced;
- `busy_timeout` and foreign-key pragma are set;
- `(account_key, ticker)` rejects duplicate rows;
- broker and strategy rows can coexist for the same ticker without field collision.

### Migration tests

- migrate a JSON fixture with strategy and broker-prefixed fields;
- preserve `entry_price` when broker average differs;
- retain unknown strategy fields in `extra_json`;
- verify the source JSON remains unchanged;
- run migration twice and assert no duplicate rows and identical strategy values;
- change the source fixture and verify default safe behavior does not overwrite DB state;
- inject an import failure and assert no partial rows or completion marker.

### Sync transaction tests

- non-empty official `result.items` snapshot commits broker rows and success history;
- empty `result.items` commits an empty broker snapshot and `success_no_positions` history;
- 401/403/429/500/timeout/malformed response preserves the prior broker and strategy state and records error status where possible;
- force a repository exception after an upsert and assert rollback of broker changes and same-transaction success history;
- partial quantity/average/market/currency changes update only broker columns;
- broker-only ticker is created without fabricated strategy entry state;
- omitted ticker removes broker state only after successful full snapshot.

### Concurrency tests

- two writers against the same `tmp_path` database serialize without corruption;
- a held writer lock causes a bounded wait and classified lock failure after the configured timeout;
- a reader during a write observes either the old or new committed combined view, never an intermediate set;
- reopen the database after concurrent operations and run `PRAGMA integrity_check`.

### Regression strategy

Run the existing 31-test suite unchanged after new tests. Existing Toss failure-safe tests remain authoritative for 401/403/429/500/timeout behavior. If tests currently depend on `positions.json`, update only their state fixture/injection so they use an isolated state service while preserving the same returned position-map assertions. Do not alter Telegram/Gemini/Spring/daily-report expectations.

## Expected Files

### New files

- `state/__init__.py`
- `state/database.py`
- `state/repository.py`
- `state/service.py`
- `state/migration.py` (only if migration logic is large enough to warrant separation)
- `tests/test_state_repository.py`
- `tests/test_state_migration.py`
- `tests/test_state_sync_service.py`

### Modified files

- `broker/sync_service.py`: call state service for atomic snapshot application and safe fallback
- `broker/reconciler.py`: reuse or narrow existing merge policy so it maps to separated state without overwriting strategy fields
- `broker/models.py`: add state/sync result fields only if current models cannot represent them
- `bot.py`: minimal state-service initialization or compatibility adapter wiring
- `daily_report.py`: minimal injection/binding change if it does not already use the shared loader
- `tests/conftest.py`: optional fixtures for `tmp_path` state service; no production DB path
- `requirements.txt`: no change expected because `sqlite3` is standard library

### Files explicitly not changed for feature behavior

- Toss order APIs or order execution modules: none added
- WebSocket clients: none added
- Telegram/Gemini/Spring business logic: no changes
- `positions.json`: retained as source/recovery artifact, not deleted

## Implementation Order

1. Confirm the current `load_positions()`/`save_positions()` call graph and identify the narrow adapter seam without changing behavior.
2. Add `state/database.py` with path resolution, connection pragmas, WAL verification, schema initialization, and transaction context manager.
3. Add repository SQL methods and schema tests for broker, strategy, history, and metadata tables.
4. Add combined compatibility view and `load_positions()`/`save_positions()` adapter behavior.
5. Implement JSON migration with explicit field allowlists, metadata digest, idempotent retry rules, source retention, and isolated tests.
6. Refactor the state mutation portion of `broker/sync_service.py` to validate outside the transaction and apply successful full snapshots atomically.
7. Add empty snapshot, rollback, API failure, partial-change, broker-only, and omitted-ticker tests.
8. Add minimal `bot.py` and `daily_report.py` wiring while preserving existing call order and outputs.
9. Add concurrency/WAL/locking tests and verify SQLite integrity after concurrent operations.
10. Run formatting/static checks applicable to the repository, `git diff --check`, the new state tests, and the complete existing 31-test regression suite.

## Execution Gate

Implementation may begin only when:

- the default DB path and account-key policy are accepted;
- the broker/strategy field allowlists and stale-ticker policy are accepted;
- the WAL and 5-second busy-timeout policy are accepted;
- the failure-history transaction choice is accepted;
- the compatibility adapter contract is confirmed to preserve current position-map callers;
- no order or WebSocket scope has been added.

## Risks and Mitigations

- **Unexpected legacy fields**: preserve unknown strategy data in `extra_json` and test round-trip behavior.
- **Changed JSON after migration**: use digest marker and safe no-overwrite default rather than silently importing stale/changed data.
- **WAL filesystem limitations**: verify actual mode and fail visibly or use a documented fallback.
- **Concurrent GitHub Actions runs**: short `BEGIN IMMEDIATE` transactions, 5-second busy timeout, and classified lock failures; add process lock only if tests demonstrate a need.
- **Compatibility regression**: keep the combined position-map adapter and run all existing tests before considering the feature complete.

## Complexity Tracking

No ORM, PostgreSQL service, distributed lock, order subsystem, or WebSocket subsystem is introduced. The only intentional complexity is the explicit two-domain state model and transaction/migration boundary required by the spec.
