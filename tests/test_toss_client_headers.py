import json
from unittest.mock import Mock

from broker.toss_client import TossClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_toss_client_uses_documented_endpoint_and_account_header():
    session = Mock()
    response = FakeResponse(200, {"status": "success", "data": {"positions": []}})
    session.get.return_value = response

    client = TossClient(
        base_url="https://openapi.tossinvest.com",
        access_token="token-123",
        account_id="ACC-001",
        timeout=12,
        session=session,
    )

    client.fetch_holdings()

    session.get.assert_called_once()
    call_args = session.get.call_args
    assert call_args.kwargs["timeout"] == 12
    assert call_args.args[0] == "https://openapi.tossinvest.com/api/v1/holdings"
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer token-123"
    assert call_args.kwargs["headers"]["X-Tossinvest-Account"] == "ACC-001"


def test_toss_client_keeps_error_statuses_out_of_empty_holdings_path():
    session = Mock()
    response = FakeResponse(401, {"code": 401, "message": "Unauthorized"})
    session.get.return_value = response

    client = TossClient(
        base_url="https://openapi.tossinvest.com",
        access_token="token-123",
        account_id="ACC-001",
        timeout=12,
        session=session,
    )

    result = client.fetch_holdings()

    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_ERROR"
    assert result.get("message") is not None


def test_normalize_holdings_supports_documented_payload_shape():
    payload = {
        "status": "success",
        "data": {
            "positions": [
                {"ticker": "AAPL", "quantity": 4, "averagePrice": 102.5, "market": "US"},
                {"ticker": "MSFT", "quantity": 2, "averagePrice": 320.0, "market": "US"},
            ]
        },
    }

    normalized = __import__("broker.toss_client", fromlist=["normalize_holdings"]).normalize_holdings(payload)

    assert normalized["status"] == "success"
    assert normalized["positions"]["AAPL"]["quantity"] == 4.0
    assert normalized["positions"]["AAPL"]["average_price"] == 102.5
    assert normalized["positions"]["MSFT"]["quantity"] == 2.0
