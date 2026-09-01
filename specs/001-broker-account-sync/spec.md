# Feature Specification: Broker Account Sync

**Feature Branch**: `[001-broker-account-sync]`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "토스증권 Open API를 이용해 실제 보유 주식 계좌 상태를 봇과 동기화한다. 목표: - 봇 실행 전 실제 보유종목 조회 - 실제 계좌 보유 상태를 broker position의 source of truth로 사용 - 수동 매수/매도 반영 - 실제 평균매수가와 전략 진입가 분리 - API 실패 시 기존 로컬 상태 보존 - 인증정보는 환경변수/secret 사용 - pytest 회귀 테스트 추가 - 기존 Telegram, Gemini, Spring webhook, daily_report 기능 유지 - 기존 시스템 전면 재작성 금지"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Synchronize actual holdings before trading decisions (Priority: P1)

When the bot starts, it must load the current account holdings from the broker before evaluating buy or sell opportunities. The broker position list becomes the trusted source of truth for what is genuinely owned, so the bot does not act on stale local data.

**Why this priority**: This prevents duplicate buys, incorrect position counts, and stale strategy assumptions before the bot decides to place or close trades.

**Independent Test**: The bot can be started with a known broker snapshot and a local position file, and the resulting decisions can be validated against the broker-held positions.

**Acceptance Scenarios**:

1. **Given** the broker account shows a valid open position, **When** the bot performs its startup sync, **Then** the current broker holdings are loaded and treated as the active truth for that account.
2. **Given** the local position file contains a ticker that is no longer held by the broker, **When** the sync runs, **Then** the bot removes or updates the stale local state before evaluating the strategy.
3. **Given** the broker account contains holdings that were added manually outside the bot, **When** the next sync runs, **Then** those manual positions are reflected in the bot’s working state without requiring a full rewrite.

---

### User Story 2 - Keep strategy entry pricing separate from actual broker average cost (Priority: P1)

The bot must distinguish the real account average purchase price from the internal strategy entry price used for risk and exit calculations. This keeps manual broker activity and strategy assumptions aligned without collapsing into one value.

**Why this priority**: Users may add or sell positions outside the strategy, and the bot must avoid mixing operational account facts with trading plan assumptions.

**Independent Test**: A position can be created both through the broker and through the bot’s internal strategy, and the broker average price remains intact while the strategy entry remains traceable.

**Acceptance Scenarios**:

1. **Given** a user buys shares outside the strategy, **When** the broker sync runs, **Then** the actual average purchase price is updated without overwriting the strategy’s planned entry values.
2. **Given** the strategy has an internal entry price and the broker shows a different actual average cost, **When** the bot evaluates risk and exits, **Then** only the correct values are used for each purpose and the distinction is preserved.

---

### User Story 3 - Preserve local state when the broker API fails (Priority: P2)

If the broker API is unavailable, rate-limited, or rejects authentication, the bot must keep the last known local state and avoid destructive changes. A failed sync must be treated as a degraded but safe operating mode.

**Why this priority**: A temporary broker outage should not erase valid local holdings or cause a false sell or buy decision.

**Independent Test**: The bot can be run with a simulated API failure and the local position file remains unchanged while warnings and retry behavior are logged.

**Acceptance Scenarios**:

1. **Given** the broker sync call fails due to authentication or network issues, **When** the bot continues execution, **Then** the local state remains intact and no destructive action is taken.
2. **Given** a sync failure occurs after a recent manual buy or sell, **When** the next successful sync runs, **Then** the broker data is reconciled to the latest state and the local file is corrected.

---

### User Story 4 - Secure credentials and maintain existing bot features (Priority: P2)

Authentication material must be kept in environment variables or secret storage, and the broker sync feature must coexist with the current Telegram, Gemini, Spring webhook, and daily reporting workflows without forcing a rewrite.

**Why this priority**: Operational reliability depends on secure credentials and preserving existing user-facing alerts and downstream integrations.

**Independent Test**: The bot can run in a standard environment with configured credentials and all notification flows continue to operate without regression.

**Acceptance Scenarios**:

1. **Given** the broker credentials are defined through environment variables or a secret store, **When** the sync executes, **Then** the credentials are loaded without hardcoded values in the codebase.
2. **Given** the existing Telegram, Gemini, Spring webhook, and daily_report features are active, **When** the broker sync is enabled, **Then** those features remain operational and their behavior stays intact.

### Edge Cases

- What happens when the broker account is temporarily unavailable during startup?
- How does the system handle a ticker that exists locally but is absent in the broker account?
- What happens when the user manually sells a position after the bot last synced?
- What happens when the broker returns partial or inconsistent position data?
- What happens when broker credentials are missing or invalid?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The bot MUST fetch the current account holdings before executing its regular trading checks for each run.
- **FR-002**: The broker account holdings MUST be treated as the source of truth for currently owned positions when the sync succeeds.
- **FR-003**: The bot MUST reconcile local positions with broker positions so stale or manually closed positions are removed or updated before strategy decisions are made.
- **FR-004**: The system MUST distinguish the actual broker average purchase price from the strategy entry price used by the bot for risk and exit logic.
- **FR-005**: The bot MUST reflect manual buy and sell activity observed in the broker account during the next successful sync cycle.
- **FR-006**: If the broker API fails, the bot MUST keep the previous local state intact and continue in a safe degraded mode without forcing destructive changes.
- **FR-007**: The bot MUST use environment variables or a secret store for broker credentials and MUST NOT require hardcoded account secrets in repository files.
- **FR-008**: The broker sync feature MUST coexist with the existing Telegram alerts, Gemini analysis, Spring webhook notifications, and daily report workflow without requiring a full system rewrite.
- **FR-009**: The system MUST log sync success, reconciliation results, and failure conditions so users can inspect what changed and why.
- **FR-010**: The system MUST keep the broker-sync behavior backward compatible with current local position handling when no broker data is available.

### Key Entities *(include if feature involves data)*

- **Broker Position**: The actual inventory reported by the broker account, including ticker, quantity, and average cost.
- **Local Position**: The bot’s stored position state used for strategy decisions and notifications.
- **Strategy Entry**: The internal price used by the bot’s trading logic for risk and take-profit calculations.
- **Sync Result**: The reconciliation outcome for a given run, including whether the broker state was applied, preserved, or failed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When the broker sync succeeds, the bot uses the actual account position snapshot before evaluating trading actions for the same run.
- **SC-002**: When the broker API fails, the bot keeps the previous local position state unchanged and raises an explicit warning or log entry without producing destructive actions.
- **SC-003**: Manual broker transactions are reflected in the bot within a single following sync cycle, without requiring a full restart or data reset.
- **SC-004**: Users can distinguish real broker cost information from the strategy’s internal entry price in the bot’s position view and decision logic.
- **SC-005**: Existing Telegram, Gemini, Spring webhook, and daily_report functions continue to operate during and after broker synchronization without a regression in core notification behavior.

## Assumptions

- The broker account is accessible with valid credentials stored in environment variables or a secret manager.
- The sync feature is additive to the current bot behavior and does not replace the established strategy engine.
- Manual account actions outside the bot are expected and should be reconciled on the next successful sync.
- A failed broker call is treated as a temporary operational issue rather than a reason to overwrite durable local state.
- The current trading logic and notification stack remain in place while the broker state is incorporated as the source of truth for actual holdings.
