import json
from pathlib import Path

import pandas as pd


def _price_df(prices):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"Close": prices}, index=idx)


def test_sell_alert_failure_keeps_position(bot_module, monkeypatch, tmp_path):
    ticker = "TEST"
    bot_module.TARGETS = [{"ticker": ticker, "name": "테스트", "market": "US"}]
    bot_module.TICKER_MARKET_MAP = {ticker: "US"}

    positions_path = tmp_path / "positions.json"
    initial = {
        ticker: {
            "name": "테스트",
            "entry_price": 100.0,
            "highest_price": 150.0,
            "opened_at": "2026-03-26 09:00",
            "market": "US",
        }
    }
    positions_path.write_text(json.dumps(initial, ensure_ascii=False), encoding="utf-8")
    bot_module.POSITIONS_FILE = str(positions_path)

    monkeypatch.setattr(
        bot_module,
        "get_market_risk",
        lambda: {"level": "Normal", "score": 50, "summary": "risk"},
    )
    monkeypatch.setattr(bot_module, "get_latest_news", lambda _name: "news")
    monkeypatch.setattr(bot_module, "get_ai_comment", lambda **_kwargs: "ai")
    monkeypatch.setattr(bot_module, "send_telegram", lambda _msg: False)

    monkeypatch.setattr(
        bot_module.yf,
        "download",
        lambda *_args, **_kwargs: _price_df([100.0] * 68 + [100.0, 220.0]),
    )

    bot_module.analyze_market()

    final_positions = json.loads(Path(bot_module.POSITIONS_FILE).read_text(encoding="utf-8"))
    assert ticker in final_positions


def test_buy_alert_failure_does_not_create_position(bot_module, monkeypatch, tmp_path):
    ticker = "TEST"
    bot_module.TARGETS = [{"ticker": ticker, "name": "테스트", "market": "US"}]
    bot_module.TICKER_MARKET_MAP = {ticker: "US"}

    positions_path = tmp_path / "positions.json"
    positions_path.write_text("{}", encoding="utf-8")
    bot_module.POSITIONS_FILE = str(positions_path)

    monkeypatch.setattr(
        bot_module,
        "get_market_risk",
        lambda: {"level": "Normal", "score": 50, "summary": "risk"},
    )
    monkeypatch.setattr(bot_module, "get_latest_news", lambda _name: "news")
    monkeypatch.setattr(bot_module, "get_ai_comment", lambda **_kwargs: "ai")
    monkeypatch.setattr(bot_module, "send_telegram", lambda _msg: False)

    monkeypatch.setattr(
        bot_module.yf,
        "download",
        lambda *_args, **_kwargs: _price_df([100.0] * 68 + [100.0, 1.0]),
    )

    bot_module.analyze_market()

    final_positions = json.loads(Path(bot_module.POSITIONS_FILE).read_text(encoding="utf-8"))
    assert final_positions == {}
