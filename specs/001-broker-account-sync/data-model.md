# Data Model: Broker Account Sync

## Overview

This feature adds a broker-backed position model while preserving the existing `positions.json` shape for strategy state. The design keeps actual account facts separate from strategy bookkeeping.

## Entities

### BrokerPosition

Represents the real account holdings reported by Toss Securities.

Fields:
- `ticker`: symbol string used as the identity key
- `quantity`: integer or float quantity currently held
- `average_price`: actual average purchase price from the account
- `market`: market code such as `KR` or `US`
- `last_updated_at`: ISO timestamp when data was synced
- `source`: `toss`
- `raw`: optional map containing the original API payload for debugging and traceability

Validation rules:
- `ticker` must be non-empty
- `quantity` must be numeric and non-negative
- `average_price` must be numeric and non-negative
- `market` must be one of the supported values or unknown/normalized

### StrategyPosition

Represents the bot's internal trading position data that is used for strategy decisions.

Fields:
- `name`: display name or ticker label
- `entry_price`: strategy buy entry price
- `highest_price`: highest price observed during the position lifecycle
- `opened_at`: ISO date/time when the strategy opened the position
- `market`: market code
- `target1_hit`: boolean if first target has been reached
- `trailing_active`: boolean if trailing stop logic is active
- `stop_loss_pct`: ratio used by risk policy
- `target1_pct`: ratio used by first target
- `target2_pct`: ratio used by final target
- `last_synced_at`: timestamp of last broker sync

Validation rules:
- strategy fields remain optional and may be absent for newly discovered broker-only positions
- `entry_price` can be missing until the strategy decides to buy
- `highest_price` may be `null` until the position is tracked by the bot

### SyncResult

Represents the outcome of the broker reconciliation run.

Fields:
- `status`: `success`, `success_no_positions`, `error`, or `partial`
- `broker_positions_count`: count of normalized broker positions
- `local_positions_count`: count of local positions before reconciliation
- `updated_tickers`: list of tickers changed by the sync
- `removed_tickers`: list of tickers pruned because they were no longer held
- `added_tickers`: list of newly discovered positions
- `failure_reason`: short reason when the status is `error`
- `synced_at`: ISO timestamp

State transitions:
- `success` → broker data applied and local state updated
- `success_no_positions` → valid zero-holdings response, no destructive change
- `error` → stored local state retained; no overwrite
- `partial` → some values updated; missing or conflicting data still retains prior state for ambiguous records

## Relationships

- A single account can produce many `BrokerPosition` records.
- `StrategyPosition` entries are derived from or mapped to broker-held records, but they are not identical objects.
- Reconciliation aligns `BrokerPosition` with `StrategyPosition` by ticker key while preserving the strategy-only fields.
- The `SyncResult` records a single reconciliation operation for observability and debugging.

## Backward compatibility

The current local JSON position map is kept as-is for this phase. If a ticker exists in the local JSON but not in the broker response, the reconciler will treat that as stale state only when the broker call succeeded and returned a valid full or partial account snapshot.
