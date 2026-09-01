# Contract: Toss Account Sync Interface

## Purpose

This contract defines the narrow adapter boundary between the external Toss Securities API and the internal bot state model. All code outside the broker adapter layer operates only on normalized internal data.

## External contract (adapter input)

The Toss client is responsible for fetching a holdings snapshot and returning a normalized structure shaped like:

```json
{
  "status": "success",
  "positions": [
    {
      "ticker": "005930.KS",
      "quantity": 10,
      "average_price": 70000,
      "market": "KR",
      "last_updated_at": "2026-09-01T09:00:00Z"
    }
  ]
}
```

## Internal contract (bot-facing output)

The normalized model consumed by the reconciler is:

```python
{
  "ticker": "005930.KS",
  "quantity": 10,
  "average_price": 70000,
  "market": "KR",
  "last_updated_at": "2026-09-01T09:00:00Z",
  "source": "toss",
}
```

## Error contract

The adapter must return an explicit error classification instead of silently treating failure as an empty account:

```json
{
  "status": "error",
  "error_code": "AUTH_FAILED",
  "message": "Toss token invalid or expired"
}
```

## Behavior requirements

- Empty holdings returns `status: "success"` with an empty list, not `error`.
- Authentication, timeout, and server errors return `status: "error"`.
- The reconciler must not delete or rewrite local state when the status is `error`.
- The client must expose mockable methods for unit testing and stubbed API integration tests.
