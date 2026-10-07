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
    response = FakeResponse(200, {"status": "success", "result": {"items": []}})
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


def test_normalize_holdings_uses_official_result_items_shape_for_kr_and_us():
    payload = {
        "status": "success",
        "result": {
            "items": [
                {"symbol": "005930", "marketCountry": "KR", "currency": "KRW", "quantity": "4", "averagePurchasePrice": "102.5"},
                {"symbol": "AAPL", "marketCountry": "US", "currency": "USD", "quantity": "2", "averagePurchasePrice": "320.0"},
            ]
        },
    }

    normalized = __import__("broker.toss_client", fromlist=["normalize_holdings"]).normalize_holdings(payload)

    assert normalized["status"] == "success"
    assert normalized["positions"]["005930"]["quantity"] == 4.0
    assert normalized["positions"]["005930"]["average_price"] == 102.5
    assert normalized["positions"]["005930"]["market"] == "KR"
    assert normalized["positions"]["AAPL"]["currency"] == "USD"


def test_normalize_holdings_official_empty_items_is_valid_empty_snapshot():
    from broker.toss_client import normalize_holdings
    assert normalize_holdings({"status": "success", "result": {"items": []}}) == {
        "status": "success_no_positions", "positions": []
    }


def test_accounts_account_seq_is_used_as_holdings_account_header():
    session = Mock()
    session.get.side_effect = [
        FakeResponse(200, {"status": "success", "result": {"accounts": [{"accountSeq": "SEQ-42"}]}}),
        FakeResponse(200, {"status": "success", "result": {"items": []}}),
    ]
    accounts_client = TossClient(base_url="https://openapi.tossinvest.com", access_token="token-123", account_id="unused", session=session)
    accounts = accounts_client.fetch_accounts()
    account_seq = accounts["result"]["accounts"][0]["accountSeq"]
    holdings_client = TossClient(base_url="https://openapi.tossinvest.com", access_token="token-123", account_id=account_seq, session=session)
    holdings_client.fetch_holdings()
    assert session.get.call_args_list[0].args[0].endswith("/api/v1/accounts")
    assert session.get.call_args_list[1].kwargs["headers"]["X-Tossinvest-Account"] == "SEQ-42"
