# Feature Specification: State Reliability

**Feature Branch**: `[003-state-reliability]`

**Created**: 2026-09-09

**Status**: Draft

**Input**: User request to replace `positions.json` as the primary persistent state with a reliable SQLite state layer while preserving the existing read-only Toss holdings synchronization, strategy behavior, and notification integrations.

## Scope

This feature introduces SQLite-backed persistence for broker and strategy state, an idempotent migration path from the existing `positions.json`, transactional Toss holdings synchronization, and sync history.

This feature does not add Toss order creation, conditional orders, automated order execution, order submission, or WebSocket order-event ingestion. Future order and event storage may extend the schema, but order tables are not required here.

The existing Telegram, Gemini, Spring webhook, `daily_report.py`, and strategy logic remain in scope for regression compatibility. A full rewrite of `bot.py` is explicitly out of scope; a repository/service adapter that keeps `load_positions()` and `save_positions()` changes small is preferred.

## User Scenarios & Testing

### User Story 1 - Use SQLite as the durable state source (Priority: P1)

When the bot starts, it can load its position state from SQLite without requiring `positions.json` to exist. SQLite is the primary persistent state, while the JSON file is retained only as a migration source or explicitly supported compatibility artifact.

**Independent Test**: Start the state layer with a temporary SQLite database and no `positions.json`; load and save positions, restart the state layer, and confirm the same state is available.

**Acceptance Scenarios**:

1. **Given** a valid SQLite database containing broker and strategy state, **when** the bot loads positions, **then** the adapter returns the combined position view required by the existing strategy and reporting callers.
2. **Given** no `positions.json` exists, **when** the bot starts with a valid SQLite database, **then** it operates without attempting to recreate or require the JSON file.
3. **Given** an existing caller uses `load_positions()` or `save_positions()`, **when** the state adapter is enabled, **then** the caller requires only minimal changes and receives behavior compatible with the current position-map contract.

### User Story 2 - Keep broker facts separate from strategy state (Priority: P1)

The state layer stores actual Toss holdings and strategy bookkeeping as separate records. Broker average purchase price is never used as a replacement for the strategy's `entry_price`.

**Independent Test**: Store a strategy position with `entry_price=90` and sync a broker position with `broker_average_price=102.5`; retrieve both records and confirm both values remain unchanged in their respective domains.

**Acceptance Scenarios**:

1. **Given** a broker holding, **when** it is persisted, **then** the broker record contains `ticker`, `broker_quantity`, `broker_average_price`, `broker_market`, `broker_currency`, `broker_last_updated_at`, and `broker_source`.
2. **Given** a strategy position, **when** a broker snapshot is synchronized, **then** `entry_price`, `highest_price`, `target1_hit`, `trailing_active`, `opened_at`, and other strategy-only fields are preserved.
3. **Given** a ticker exists only in a successful broker snapshot, **when** it is reconciled, **then** a broker record is created without inventing strategy values.
4. **Given** a ticker exists only in strategy state, **when** the broker snapshot is successful and authoritative, **then** stale broker alignment is handled according to the existing sync behavior without copying broker values into strategy fields.

### User Story 3 - Apply Toss sync atomically (Priority: P1)

Each successful Toss holdings snapshot is applied as one transaction. A valid empty snapshot is a successful account state; an API or parsing failure is an error state and must preserve the prior database state.

**Independent Test**: Seed a temporary database, inject a failure after a planned write, and confirm the database contains the exact pre-sync state. Repeat with `result.items=[]` and confirm the empty snapshot commits normally.

**Acceptance Scenarios**:

1. **Given** a valid non-empty `result.items` snapshot, **when** synchronization completes, **then** all broker changes and corresponding sync-history success data commit together.
2. **Given** `result.items=[]`, **when** synchronization completes, **then** the operation is recorded as a successful empty snapshot and stale broker holdings are reconciled according to the established success behavior.
3. **Given** a 401, 403, 429, 500, timeout, malformed response, or other API failure, **when** synchronization runs, **then** no broker or strategy state is changed and the operation is recorded as an error.
4. **Given** an exception occurs during reconciliation or persistence, **when** the transaction exits, **then** all writes from that synchronization are rolled back with no partial state visible.
5. **Given** a sync failure, **when** the bot continues in degraded mode, **then** existing state remains available and the failure is not converted to empty holdings.

### User Story 4 - Migrate existing JSON state safely (Priority: P1)

A first run can import existing `positions.json` state into SQLite without losing strategy metadata. Migration is idempotent and does not immediately delete the source JSON.

**Independent Test**: Migrate a fixture containing strategy fields and broker fields twice into a temporary database, then verify the second run creates no duplicates and all original strategy values remain unchanged.

**Acceptance Scenarios**:

1. **Given** a valid legacy `positions.json`, **when** migration runs, **then** strategy state is stored in `strategy_position` and recognizable broker metadata is stored in `broker_position`.
2. **Given** migration has already succeeded, **when** migration runs again, **then** it is idempotent and does not duplicate records or overwrite preserved strategy state with different defaults.
3. **Given** migration succeeds, **when** the process finishes, **then** the original JSON remains available for recovery and audit; automatic deletion is not performed.
4. **Given** invalid or partially unreadable JSON, **when** migration runs, **then** it fails safely without replacing existing SQLite state and reports an actionable error.

### User Story 5 - Remain safe under concurrent execution (Priority: P2)

Two local or GitHub Actions executions may access the same SQLite file without corrupting state or exposing partially committed snapshots.

**Independent Test**: Run concurrent read/write or sync attempts against a temporary database and confirm each reader sees a committed state, writers serialize or fail with a classified retryable lock error, and the database remains valid.

**Acceptance Scenarios**:

1. **Given** concurrent synchronization attempts, **when** they write the same database, **then** SQLite locking and transaction rules prevent corruption and partial commits.
2. **Given** a transient `database is locked` condition, **when** the configured busy timeout is exhausted, **then** the operation returns a classified failure and preserves the last committed state.
3. **Given** concurrent readers during a write, **when** they load state, **then** they see either the previous committed snapshot or the new committed snapshot, never an intermediate one.
4. **Given** process-level locking is needed by the implementation, **when** it is introduced, **then** it remains narrow, documented, and does not add unnecessary coordination complexity.

### User Story 6 - Record synchronization history (Priority: P2)

Each synchronization attempt can be inspected independently from current state.

**Independent Test**: Execute successful, empty, and failed syncs and query history from a temporary database.

**Acceptance Scenarios**:

1. **Given** any sync attempt, **when** it starts and completes, **then** a `sync_history` record can represent `source`, `status`, timestamps, and outcome details.
2. **Given** a successful sync, **then** `changed_count` reflects the number of changed broker/state records according to the defined counting rule.
3. **Given** a failure, **then** `error_code` and `error_message` are retained without storing credentials or access tokens.

## Functional Requirements

- **FR-001**: SQLite MUST be the primary persistent state for positions after this feature is enabled.
- **FR-002**: The state schema MUST represent broker state separately from strategy state, keyed by ticker and designed so each domain can evolve independently.
- **FR-003**: The broker state MUST support `ticker`, `broker_quantity`, `broker_average_price`, `broker_market`, `broker_currency`, `broker_last_updated_at`, and `broker_source`.
- **FR-004**: The strategy state MUST support at minimum `ticker`, `entry_price`, `highest_price`, `target1_hit`, `trailing_active`, `opened_at`, and other existing strategy-only fields required by the current bot.
- **FR-005**: The persistence layer MUST NOT copy `broker_average_price` into `strategy_position.entry_price` during sync or migration.
- **FR-006**: A successful Toss holdings snapshot MUST be applied within one database transaction.
- **FR-007**: A failed, timed-out, unauthorized, rate-limited, server-error, or malformed Toss response MUST leave the last committed broker and strategy state unchanged.
- **FR-008**: A valid empty holdings snapshot MUST be represented as a successful empty result and MUST NOT be treated as an API failure.
- **FR-009**: Any exception during a sync transaction MUST cause rollback of all writes from that sync; partial broker, strategy, or history updates MUST NOT become visible.
- **FR-010**: SQLite concurrency policy MUST be documented and implemented, including transaction boundaries, busy timeout, and locking behavior.
- **FR-011**: WAL mode MUST be evaluated. The preferred policy is to enable WAL for the state database because it improves read concurrency while preserving SQLite transactional writes; the implementation MUST document any environment-specific fallback or reason not to enable it.
- **FR-012**: Migration from `positions.json` MUST preserve existing strategy values, be idempotent, and retain the source JSON after successful migration.
- **FR-013**: Migration MUST be safe to retry after interruption and MUST not duplicate ticker records or corrupt an already migrated database.
- **FR-014**: Existing `load_positions()` and `save_positions()` behavior SHOULD be preserved through a small adapter/service boundary; changes to `bot.py` MUST remain minimal and no broad rewrite is allowed.
- **FR-015**: Existing Toss read-only holdings synchronization MUST remain supported, including the official `result.items` response contract and failure-safe behavior.
- **FR-016**: Telegram, Gemini, Spring webhook, and `daily_report.py` behavior MUST remain compatible with the combined state view returned by the adapter.
- **FR-017**: The system MUST provide a `sync_history` record with `id`, `source`, `status`, `started_at`, `completed_at`, `changed_count`, `error_code`, and `error_message`.
- **FR-018**: Sync history MUST NOT persist access tokens, account secrets, or other credentials.
- **FR-019**: The schema MUST leave an explicit extension path for future order history and WebSocket order events, but implementation of an order table is not required for this feature.
- **FR-020**: Tests MUST use `tmp_path` or an equivalent isolated temporary SQLite database; tests MUST NOT share the production SQLite file.
- **FR-021**: Existing regression tests MUST continue to pass, including broker sync failure-safe tests and current bot/reporting tests.

## Non-Functional Requirements

- State transitions MUST be auditable through sync history without exposing secrets.
- Reads MUST return a consistent combined view of broker and strategy records.
- Database initialization MUST be deterministic and safe to run repeatedly.
- The implementation MUST keep the current JSON position-map compatibility surface where practical so unrelated integrations are not rewritten.
- No requirement in this feature authorizes real order creation, order cancellation, conditional-order management, or automated trading execution.

## Key Entities

### BrokerPosition

The latest successful read-only holdings fact from Toss, including quantity, average purchase price, market, currency, update time, and source. It is not strategy intent.

### StrategyPosition

The bot's strategy bookkeeping for a ticker, including entry price, high-water mark, target and trailing flags, lifecycle timestamps, and other strategy-specific values. It is not the broker's accounting record.

### SyncHistory

An append-oriented record of a broker synchronization attempt. It captures status and timing independently of the current position tables.

### CombinedPositionView

An adapter-level compatibility representation assembled from the broker and strategy tables for existing `load_positions()`, strategy, notification, and reporting callers. It MUST preserve domain-specific field names and MUST NOT collapse average cost into entry price.

## Data and Transaction Rules

- The logical identity of a position is `(account, ticker)` where account scoping is retained if the current runtime supports more than one account; otherwise the single configured Toss account is the initial scope.
- Broker and strategy records may be created or updated independently, but a successful holdings synchronization applies its broker snapshot and its related reconciliation/history outcome atomically.
- A sync transaction starts before any state mutation and commits only after validation, reconciliation, and history completion succeed.
- On rollback, the previous broker state, strategy state, and last committed history remain intact. An implementation may record a failed history row in a separate transaction only if it cannot expose partial sync state and documents that choice.
- Empty holdings is a valid committed snapshot. Failure is never represented by deleting all holdings.
- `changed_count` MUST use one documented unit consistently, such as changed ticker records, and MUST be tested.

## SQLite Concurrency and Durability Policy

- Use short explicit write transactions and avoid holding a transaction across network calls. Fetch and validate Toss data before opening the state mutation transaction.
- Configure a bounded busy timeout so concurrent writers wait briefly rather than immediately corrupting or silently dropping state.
- Prefer WAL mode for the primary SQLite database to allow readers during writes. The implementation MUST verify the resulting journal mode and gracefully report initialization failure rather than silently claiming WAL is active.
- Use a single connection per operation or a clearly managed connection boundary; do not share unsafe connections across threads or processes.
- A process-level lock is optional and should be added only if SQLite busy handling is insufficient for the observed execution model. If used, the lock MUST cover only the state mutation section and MUST be released on exceptions.
- A lock timeout or SQLite error is a sync failure: preserve the last committed state and write a safe, non-secret error classification where possible.

## Migration Rules

- Migration reads the legacy JSON map without modifying or deleting it.
- Existing strategy keys are copied to `strategy_position` unchanged where supported; unknown strategy keys require an explicit compatibility strategy rather than silent loss.
- Existing broker-prefixed keys are mapped to `broker_position`; legacy non-prefixed `quantity`/`average_price` fields MUST NOT overwrite `entry_price`.
- Migration is idempotent by stable `(account, ticker)` identity and a migration marker or equivalent deterministic upsert rule.
- A migration that fails partway MUST roll back its database transaction and remain safe to retry.

## Out of Scope

- Toss order creation or submission.
- Conditional orders, automated buy/sell execution, order cancellation, or position execution workflows.
- WebSocket order-event ingestion and an implemented order table.
- Rewriting strategy calculations, Telegram/Gemini/Spring integrations, or daily reporting.
- Removing `positions.json` automatically after migration.
- Introducing a distributed lock service or a new production database.

## Testing Requirements

The implementation plan MUST include isolated tests for:

1. JSON-to-SQLite migration with broker and strategy fields.
2. Re-running migration idempotently.
3. Broker/strategy separation, including average price versus entry price.
4. Successful transaction commit and forced rollback.
5. API failure preserving existing state.
6. Empty holdings as a successful committed snapshot.
7. Partial holdings changes and stale-position reconciliation.
8. Basic concurrent access and SQLite locking behavior.
9. WAL/busy-timeout initialization behavior according to the selected policy.
10. Existing broker, bot, Telegram/Gemini/Spring, and daily-report regression tests.

All database tests MUST create isolated databases under pytest `tmp_path`; no test may read from or write to the production database file.

## Success Criteria

- **SC-001**: The bot can load, update, and restart from SQLite with no `positions.json` present.
- **SC-002**: A representative legacy `positions.json` migrates successfully, preserves strategy state, retains the source file, and produces the same result when migration is run a second time.
- **SC-003**: A successful Toss snapshot commits broker changes atomically, while any tested failure path leaves the previous committed state unchanged.
- **SC-004**: Broker average purchase price and strategy entry price remain separately queryable and unchanged by each other's updates.
- **SC-005**: Empty holdings commits as a successful empty snapshot and is observably distinct from 401/403/429/500/timeout failures.
- **SC-006**: Concurrent access tests show no corrupted SQLite database or partially visible position snapshot.
- **SC-007**: Existing regression tests pass without adding real order execution or changing the existing notification/reporting behavior.

## Assumptions

- The initial deployment uses one configured Toss account, but the schema should not prevent future account scoping.
- The current official Toss holdings adapter remains read-only and continues to normalize `result.items`.
- SQLite is acceptable for the deployment scale and is stored at a configured local path with appropriate backup/recovery handling outside this feature.
- Existing callers can consume a combined compatibility view while the underlying persistence is split into broker and strategy records.
