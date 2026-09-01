# Tasks: Toss Account Sync

**Input**: Design documents from `/specs/001-broker-account-sync/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel when different files are touched and no dependency blocks remain
- **[Story]**: Which user story the task belongs to, using `US1`/`US2`/`US3`/`US4`
- Every task description includes the target file path and a validation method

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the minimal project structure needed for the broker sync feature without disturbing the existing trading bot.

- [ ] T001 Create the new broker module skeleton in `broker/__init__.py`, `broker/models.py`, `broker/toss_client.py`, `broker/reconciler.py`, and `broker/sync_service.py` to isolate Toss logic from `bot.py`.
- [ ] T002 [P] Add the broker sync test file `tests/test_toss_sync.py` and initial mock fixtures for a stubbed Toss HTTP client, with validation to confirm tests use mocked responses instead of a live API call.
- [ ] T003 [P] Confirm env-based config contract for secrets in `bot.py` and document required vars (`TOSS_API_BASE_URL`, `TOSS_ACCESS_TOKEN`, `TOSS_ACCOUNT_ID`) without storing any secret in source control.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the shared broker contract and state model that all user stories depend on.

- [ ] T004 Implement the canonical broker-data model in `broker/models.py` for normalized holdings entries, sync results, and error classification (`success`, `success_no_positions`, `error`, `partial`).
- [ ] T005 [P] Define the broker/strategy state separation contract in `broker/models.py` and document how strategy fields such as `entry_price`, `highest_price`, `target1_hit`, and trailing flags remain distinct from account facts like `quantity` and `average_price`.
- [ ] T006 Implement the Toss HTTP adapter contract in `broker/toss_client.py` with a mockable `fetch_holdings()` method for production use and a clear distinction between empty holdings and API failures.
- [ ] T007 [P] Add the reconciliation helper skeleton in `broker/reconciler.py` to compare local `positions.json` with broker holdings while preserving strategy-only fields and never deleting data during a failure response.
- [ ] T008 Add sync-orchestration scaffolding in `broker/sync_service.py` that coordinates fetch → normalize → reconcile → persist and returns a structured `SyncResult` object for logging and testing.

**Checkpoint**: Foundation ready. All user story tasks can proceed once the broker contract and state split are in place.

---

## Phase 3: User Story 1 - Synchronize actual holdings before trading decisions (Priority: P1)

**Goal**: Ensure the bot syncs the real account holdings from Toss before it evaluates buy/sell opportunities.

**Independent Test**: Run the sync flow against a mocked broker snapshot and confirm the bot sees the real holdings before `analyze_market()` executes.

### Tests for User Story 1

- [ ] T009 [P] [US1] Add failing unit test in `tests/test_toss_sync.py` for `fetch_holdings()` returning a valid broker snapshot with multiple positions and verify the normalized structure matches the expected ticker/quantity/average price model.
- [ ] T010 [P] [US1] Add failing unit test in `tests/test_toss_sync.py` for an empty holdings response and verify it is classified as `success_no_positions`, not as an API error.
- [ ] T011 [US1] Add failing regression test in `tests/test_toss_sync.py` that exercises the sync invocation order and confirms `sync_service` is called before market analysis in the bot run path.

### Implementation for User Story 1

- [ ] T012 [US1] Implement the normalization layer in `broker/toss_client.py` and `broker/models.py` to convert raw Toss holdings payloads into the canonical internal broker position structure with ticker, quantity, average price, market, and timestamp metadata.
- [ ] T013 [US1] Implement the successful snapshot reconciliation in `broker/reconciler.py` so a valid broker response updates local positions, adds new broker-held tickers, and removes only stale tickers after a successful account snapshot.
- [ ] T014 [US1] Add the sync entry point in `broker/sync_service.py` that loads local state, fetches broker holdings, normalizes them, reconciles them, and persists the merged result without altering the current `positions.json` format.
- [ ] T015 [US1] Wire the sync call into `bot.py` before `analyze_market()` so the trading logic sees current broker-backed holdings during the same execution cycle, while leaving unrelated trading logic and reporting functions unchanged.
- [ ] T016 [US1] Validate with `python -m pytest tests/test_toss_sync.py -q` and confirm the sync ordering and successful snapshot updates pass with mock responses.

**Checkpoint**: User Story 1 is independently functional and can be validated without live Toss API access.

---

## Phase 4: User Story 2 - Separate broker position from strategy position (Priority: P1)

**Goal**: Preserve real account facts separately from the strategy’s internal trading state.

**Independent Test**: A locally tracked strategy position and a broker-held position with different quantity or average price should coexist without overwriting strategy fields.

### Tests for User Story 2

- [ ] T017 [P] [US2] Add failing test in `tests/test_toss_sync.py` for a manual broker buy that creates a broker position without overwriting existing strategy metadata in `positions.json`.
- [ ] T018 [P] [US2] Add failing test in `tests/test_toss_sync.py` for a broker average-price change that updates account facts while leaving `entry_price` and `highest_price` intact.
- [ ] T019 [US2] Add failing test in `tests/test_toss_sync.py` for a manual full sell where the broker snapshot removes the ticker only after a successful sync and does not affect strategy fields unless the strategy is intentionally reset.

### Implementation for User Story 2

- [ ] T020 [US2] Extend the local `positions.json` merge contract in `broker/reconciler.py` so broker facts update `quantity` and `average_price`, while strategy fields such as `entry_price`, `highest_price`, `target1_hit`, and trailing metadata remain separate.
- [ ] T021 [US2] Add reconciliation rules in `broker/reconciler.py` for new manual buys, full manual sells, partial quantity changes, and average-price changes while preserving the legacy JSON structure and avoiding a full-state rewrite.
- [ ] T022 [US2] Update `bot.py` or the sync service log messages to clearly distinguish broker-derived values from strategy-derived values, and confirm the existing market logic remains unaffected by the extra broker metadata.
- [ ] T023 [US2] Validate with `python -m pytest tests/test_toss_sync.py -q` and confirm the state split remains correct for broker-only and strategy-only updates.

**Checkpoint**: User Story 2 passes independently and preserves strategy semantics while reconciling real account changes.

---

## Phase 5: User Story 3 - Preserve local state when Toss API fails (Priority: P2)

**Goal**: Guarantee that timeout, auth failures, and server errors do not delete or empty the current local position state.

**Independent Test**: Simulate a Toss API failure and confirm the existing local `positions.json` remains unchanged while the sync logs the failure and continues safely.

### Tests for User Story 3

- [ ] T024 [P] [US3] Add failing test in `tests/test_toss_sync.py` for a timeout or 401/403 broker response and verify the sync result status is `error` and no local positions are deleted.
- [ ] T025 [P] [US3] Add failing test in `tests/test_toss_sync.py` for a stale-state scenario where the local file contains valid positions and the broker call fails; verify the persisted file remains unchanged after synchronization.
- [ ] T026 [US3] Add failing test in `tests/test_toss_sync.py` that distinguishes `success_no_positions` from `error`, proving that an empty account is valid and a failed API call is not.

### Implementation for User Story 3

- [ ] T027 [US3] Implement error classification and guard logic in `broker/toss_client.py` and `broker/sync_service.py` so `timeout`, auth failure, and server errors return a safe `error` state instead of an empty holdings snapshot.
- [ ] T028 [US3] Harden the reconciliation flow in `broker/reconciler.py` to bail out before mutation when the broker API status is `error`, keeping the current `positions.json` file unchanged and logging the failure reason.
- [ ] T029 [US3] Add explicit handling for empty but valid holdings responses in `broker/sync_service.py` so a genuine empty account is processed as a distinct, safe case and not confused with a network failure.
- [ ] T030 [US3] Validate with `python -m pytest tests/test_toss_sync.py -q` and confirm that failure paths preserve local state and empty-account responses are handled distinctly.

**Checkpoint**: User Story 3 is independently functional and prevents destructive behavior under API failure conditions.

---

## Phase 6: User Story 4 - Secure config and preserve existing bot features (Priority: P2)

**Goal**: Keep auth and account settings externalized while ensuring the existing Telegram, Gemini, Spring webhook, and daily report flows remain stable.

**Independent Test**: The synchronized bot runs with environment-based credentials and the pre-existing integrations still execute without regression.

### Tests for User Story 4

- [ ] T031 [P] [US4] Add regression test in `tests/test_bot_core.py` or `tests/test_toss_sync.py` to verify the sync feature does not require hardcoded secrets and reads required values from environment variables.
- [ ] T032 [P] [US4] Add a non-destructive regression check that exercises `bot.py` startup or config loading and verifies the existing notification features still execute when the Toss sync is enabled.

### Implementation for User Story 4

- [ ] T033 [US4] Update the config/auth conventions in `bot.py` and the new broker module to load required values from environment variables or GitHub Secrets only, with no secret material in `config/` or the repository.
- [ ] T034 [US4] Confirm the integration boundary in `bot.py` leaves existing `send_telegram()`, `send_webhook_to_spring()`, AI-summary logic, and `daily_report.py` paths unchanged while adding the broker sync step before market analysis.
- [ ] T035 [US4] Validate with `python -m pytest tests/test_toss_sync.py tests/test_bot_core.py tests/test_daily_report.py -q` and confirm no regression exists in the legacy bot messaging/reporting flows.

**Checkpoint**: User Story 4 is complete and the feature remains additive without a full rewrite.

---

## Phase 7: Final Regression and Hardening

**Purpose**: Run the project-level verification required for the feature without expanding beyond the requested scope.

- [ ] T036 [P] Review and ensure `positions.json` backward compatibility by checking that older local JSON entries remain readable and that the sync layer only updates them under valid successful broker snapshots.
- [ ] T037 [P] Review the `bot.py` call chain to confirm the broker sync happens before `analyze_market()` and that current behavior outside that ordering remains unchanged.
- [ ] T038 [P] Run the full project regression suite with `python -m pytest -q` and confirm all existing tests still pass after the feature addition.
- [ ] T039 Confirm the implementation remains within scope by ensuring there is no SQLite migration, no large refactor of the existing system, and no change to the daily report / webhook / Telegram logic beyond the broker sync integration.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies.
- **Phase 2 (Foundational)**: Depends on Setup completion and blocks all user stories.
- **Phase 3+ (User Stories)**: All depend on the foundation being complete.
- **Phase 7 (Regression)**: Depends on all user stories being complete.

### User Story Dependencies

- **US1**: Can start after Phase 2; does not require other stories.
- **US2**: Depends on Phase 2 and should follow US1 for model/merge stability.
- **US3**: Depends on Phase 2 and should run after the normal success path is stable.
- **US4**: Depends on the broker sync logic being present; can be implemented in parallel with US3 if needed.

### Parallel Opportunities

- `T002` and `T003` can run in parallel in Phase 1.
- `T004`, `T005`, `T006`, and `T007` are independent after setup and can be split across multiple workers.
- The tests for each user story (`T009`/`T010`/`T011`, `T017`/`T018`/`T019`, `T024`/`T025`/`T026`, `T031`/`T032`) can be written in parallel before their implementation tasks.
- The final regression tasks (`T036` to `T039`) should run only after user-story completion.

---

## Implementation Strategy

### MVP First

1. Complete Setup and Foundation.
2. Implement US1 for broker sync and snapshot reconciliation.
3. Validate the sync behavior with mocked Toss data.
4. Add US2 and US3 to cover broker/strategy separation and failure handling.
5. Finish US4 for external secret config and compatibility with the existing bot features.
6. Run the full regression suite.

### Incremental Delivery

- The first usable increment is the successful sync before `analyze_market()` using the mocked broker client.
- The second increment adds broker/strategy separation and manual change reconciliation.
- The third increment hardens the feature against API failures and stale state.
- The final increment confirms the existing bot integrations still pass unchanged.

---

## Completion Criteria

The feature is ready to move from task execution to implementation review when:
- all tasks above are complete,
- all mocked broker tests pass,
- failure handling remains safe for local state,
- the app remains additive to the current trading bot,
- no SQLite migration or large refactor has been introduced.
