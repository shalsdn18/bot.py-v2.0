from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

import requests


class TossClient:
    """Minimal Toss Securities adapter for holdings queries."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        account_id: Optional[str] = None,
        timeout: int = 10,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = (base_url or os.environ.get("TOSS_API_BASE_URL") or "").rstrip("/")
        self.access_token = access_token or os.environ.get("TOSS_ACCESS_TOKEN")
        self.account_id = account_id or os.environ.get("TOSS_ACCOUNT_ID")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _build_url(self) -> str:
        if not self.base_url:
            raise ValueError("TOSS_API_BASE_URL is not configured")
        normalized = self.base_url.rstrip("/")
        if normalized.endswith("/api/v1/holdings"):
            return normalized
        if normalized.endswith("/api/v1"):
            return f"{normalized}/holdings"
        return f"{normalized}/api/v1/holdings"

    def _headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise ValueError("TOSS_ACCESS_TOKEN is not configured")
        if not self.account_id:
            raise ValueError("TOSS_ACCOUNT_ID is not configured")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Tossinvest-Account": self.account_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def fetch_holdings(self) -> Dict[str, Any]:
        try:
            response = self.session.get(
                self._build_url(),
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            return {
                "status": "error",
                "error_code": "NETWORK_ERROR",
                "message": str(exc),
            }

        if response.status_code in {401, 403}:
            return {
                "status": "error",
                "error_code": "AUTH_ERROR",
                "message": "Toss API authentication failed",
            }

        if response.status_code >= 500:
            return {
                "status": "error",
                "error_code": "SERVER_ERROR",
                "message": f"Toss API server error: HTTP {response.status_code}",
            }

        if response.status_code != 200:
            return {
                "status": "error",
                "error_code": "HTTP_ERROR",
                "message": f"Toss API returned HTTP {response.status_code}",
            }

        try:
            payload = response.json()
        except ValueError:
            payload = {"status": "error", "error_code": "INVALID_JSON", "message": "Toss API returned non-JSON"}

        status = str(payload.get("status", "success")).lower()
        if status == "error":
            return payload
        if status == "success_no_positions":
            return payload

        raw_positions = payload.get("positions", payload.get("holdings", []))
        if raw_positions is None:
            raw_positions = []

        if isinstance(raw_positions, dict):
            items: List[Dict[str, Any]] = []
            for ticker, value in raw_positions.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("ticker", ticker)
                    items.append(item)
                else:
                    items.append({"ticker": ticker, "quantity": value})
            raw_positions = items

        payload["positions"] = list(raw_positions)
        return payload


def normalize_ticker(value: Any) -> Optional[str]:
    if value is None:
        return None
    ticker = str(value).strip()
    return ticker or None


def normalize_holdings(raw_response: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(raw_response, dict):
        return {"status": "error", "error_code": "INVALID_RESPONSE", "message": "Broker response is not a dictionary"}

    status = str(raw_response.get("status", "error")).lower()
    payload_data = raw_response.get("data")
    if "error" in status or raw_response.get("code") in {400, 401, 403, 429, 500}:
        return {
            "status": "error",
            "error_code": raw_response.get("error_code") or raw_response.get("code") or "BROKER_ERROR",
            "message": raw_response.get("message", "Broker request failed"),
        }

    if status in {"success_no_positions", "success_no_holdings"}:
        return {"status": "success_no_positions", "positions": []}

    if isinstance(payload_data, dict):
        raw_positions = payload_data.get("positions", payload_data.get("holdings", payload_data.get("items", [])))
    else:
        raw_positions = raw_response.get("positions", raw_response.get("holdings", payload_data or []))

    if raw_positions is None:
        raw_positions = []

    if status in {"0000", "success", "ok", "200"} and not raw_positions:
        return {"status": "success_no_positions", "positions": []}

    if status not in {"0000", "success", "ok", "200"} and status != "":
        return {"status": "error", "error_code": "UNKNOWN_STATUS", "message": f"Unsupported status '{status}'"}

    if isinstance(raw_positions, dict):
        raw_positions = [{"ticker": ticker, **value} if isinstance(value, dict) else {"ticker": ticker, "quantity": value} for ticker, value in raw_positions.items()]

    holdings: Dict[str, Dict[str, Any]] = {}
    for item in raw_positions:
        if not isinstance(item, dict):
            continue
        ticker = normalize_ticker(item.get("ticker") or item.get("symbol") or item.get("code"))
        if not ticker:
            continue
        quantity = item.get("quantity", item.get("qty", item.get("count", 0)))
        average_price = item.get("average_price", item.get("avg_price", item.get("avgPrice", item.get("averagePrice", 0.0))))
        holdings[ticker] = {
            "ticker": ticker,
            "quantity": float(quantity or 0.0),
            "average_price": float(average_price or 0.0),
            "market": item.get("market") or item.get("market_type") or "UNKNOWN",
            "last_updated_at": item.get("last_updated_at") or item.get("updated_at") or item.get("timestamp"),
            "raw": item,
        }

    return {"status": "success", "positions": holdings}
