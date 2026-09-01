import json

from broker.sync_service import sync_positions


class StubTossClient:
    def __init__(self, response):
        self.response = response

    def fetch_holdings(self):
        return self.response


def test_sync_success_updates_broker_fields_and_keeps_strategy_values():
    local_positions = {
        "AAPL": {
            "name": "Apple",
            "entry_price": 90.0,
            "highest_price": 98.0,
            "opened_at": "2026-01-01 09:00",
            "market": "US",
            "target1_hit": True,
        }
    }
    client = StubTossClient({
        "status": "success",
        "positions": [
            {
                "ticker": "AAPL",
                "quantity": 4,
                "average_price": 102.5,
                "market": "US",
                "last_updated_at": "2026-09-01T10:00:00Z",
            }
        ],
    })

    result = sync_positions(local_positions, client=client)

    assert result["result"].status == "success"
    assert result["positions"]["AAPL"]["broker_quantity"] == 4
    assert result["positions"]["AAPL"]["broker_average_price"] == 102.5
    assert result["positions"]["AAPL"]["entry_price"] == 90.0
    assert result["positions"]["AAPL"]["highest_price"] == 98.0
    assert result["positions"]["AAPL"]["target1_hit"] is True


def test_sync_failure_preserves_existing_local_positions():
    local_positions = {
        "AAPL": {
            "name": "Apple",
            "entry_price": 90.0,
            "highest_price": 98.0,
            "market": "US",
        }
    }
    client = StubTossClient({
        "status": "error",
        "error_code": "TIMEOUT",
        "message": "Toss API timeout",
    })

    result = sync_positions(local_positions, client=client)

    assert result["result"].status == "error"
    assert result["positions"] == local_positions
    assert result["result"].failure_reason == "Toss API timeout"


def test_success_no_positions_removes_stale_local_positions():
    local_positions = {
        "AAPL": {"name": "Apple", "entry_price": 90.0, "highest_price": 98.0, "market": "US"},
        "MSFT": {"name": "Microsoft", "entry_price": 120.0, "highest_price": 130.0, "market": "US"},
    }
    client = StubTossClient({"status": "success_no_positions", "positions": []})

    result = sync_positions(local_positions, client=client)

    assert result["result"].status == "success_no_positions"
    assert result["positions"] == {}
    assert result["result"].removed_tickers == ["AAPL", "MSFT"]


def test_sync_updates_partial_change_and_average_price_without_overwriting_strategy_entry():
    local_positions = {
        "AAPL": {
            "name": "Apple",
            "entry_price": 90.0,
            "highest_price": 105.0,
            "opened_at": "2026-01-01 09:00",
            "market": "US",
            "target1_hit": False,
        }
    }
    client = StubTossClient({
        "status": "success",
        "positions": [
            {
                "ticker": "AAPL",
                "quantity": 7,
                "average_price": 96.0,
                "market": "US",
                "last_updated_at": "2026-09-01T11:00:00Z",
            }
        ],
    })

    result = sync_positions(local_positions, client=client)

    assert result["positions"]["AAPL"]["broker_quantity"] == 7
    assert result["positions"]["AAPL"]["broker_average_price"] == 96.0
    assert result["positions"]["AAPL"]["entry_price"] == 90.0
    assert result["positions"]["AAPL"]["highest_price"] == 105.0
