from __future__ import annotations

import copy
from typing import Any, Dict, List, Tuple

from .models import SyncResult


def reconcile_positions(local_positions: Dict[str, Dict[str, Any]], broker_snapshot: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], SyncResult]:
    """Merge a successful Toss snapshot into the local JSON state without clobbering strategy fields."""
    status = str(broker_snapshot.get("status", "error")).lower()

    if status == "error":
        failure_reason = broker_snapshot.get("message") or broker_snapshot.get("error_code") or "Broker sync failed"
        return copy.deepcopy(local_positions), SyncResult(status="error", failure_reason=failure_reason)

    if status in {"success_no_positions", "success_no_holdings"}:
        removed = list(local_positions.keys())
        return {}, SyncResult(status="success_no_positions", removed_tickers=removed)

    if status != "success":
        return copy.deepcopy(local_positions), SyncResult(status="error", failure_reason=f"Unsupported broker status: {status}")

    holdings = broker_snapshot.get("positions", {})
    merged: Dict[str, Dict[str, Any]] = {}
    stale_tickers: List[str] = []

    for ticker, current in local_positions.items():
        if ticker in holdings:
            entry = copy.deepcopy(current)
            broker = holdings[ticker]
            entry["broker_quantity"] = float(broker.get("quantity", 0.0))
            entry["broker_average_price"] = float(broker.get("average_price", 0.0))
            entry["broker_market"] = broker.get("market") or entry.get("market") or "UNKNOWN"
            entry["broker_last_updated_at"] = broker.get("last_updated_at")
            entry["broker_source"] = "toss"
            merged[ticker] = entry
        else:
            stale_tickers.append(ticker)

    for ticker, broker in holdings.items():
        if ticker in merged:
            continue
        merged[ticker] = {
            "name": ticker,
            "market": broker.get("market") or "UNKNOWN",
            "broker_quantity": float(broker.get("quantity", 0.0)),
            "broker_average_price": float(broker.get("average_price", 0.0)),
            "broker_market": broker.get("market") or "UNKNOWN",
            "broker_last_updated_at": broker.get("last_updated_at"),
            "broker_source": "toss",
        }

    result = SyncResult(
        status="success",
        removed_tickers=stale_tickers,
        updated_tickers=list(holdings.keys()),
        added_tickers=[ticker for ticker in holdings if ticker not in local_positions],
    )
    return merged, result
