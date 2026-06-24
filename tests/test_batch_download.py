"""Tests for batch-download logic and HISTORY_PERIOD configuration."""

import json
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prices(n: int = 70, base: float = 100.0) -> list:
    """Return *n* flat prices (useful for neutral-signal datasets)."""
    return [base] * n


def _simple_df(prices) -> pd.DataFrame:
    """Single-ticker DataFrame with a plain 'Close' column (no MultiIndex)."""
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"Close": prices}, index=idx)


def _multi_df(prices_map: dict) -> pd.DataFrame:
    """Multi-ticker DataFrame with MultiIndex columns: (field, ticker).

    This is the shape yfinance produces when *multiple* tickers are requested
    in one ``yf.download()`` call.
    """
    first_ticker = next(iter(prices_map))
    n = len(prices_map[first_ticker])
    idx = pd.date_range("2024-01-01", periods=n, freq="D")

    arrays = [
        ["Close"] * len(prices_map),
        list(prices_map.keys()),
    ]
    cols = pd.MultiIndex.from_arrays(arrays, names=["Price", "Ticker"])
    data = {("Close", t): prices_map[t] for t in prices_map}
    return pd.DataFrame(data, index=idx, columns=cols)


# ---------------------------------------------------------------------------
# A) _get_close_series — batch-parse tests
# ---------------------------------------------------------------------------

class TestGetCloseSeries:
    """Unit tests for the ``_get_close_series`` helper."""

    def test_simple_df_returns_series(self, bot_module):
        """Single-ticker plain DataFrame → returns the Close Series."""
        prices = _make_prices(70)
        df = _simple_df(prices)
        series = bot_module._get_close_series(df, "AAPL")

        assert series is not None
        assert len(series) == 70
        assert abs(series.iloc[0] - 100.0) < 1e-9

    def test_multi_df_returns_correct_ticker(self, bot_module):
        """Multi-ticker MultiIndex DataFrame → returns correct ticker's Series."""
        prices_map = {
            "AAPL": _make_prices(70, 100.0),
            "NVDA": _make_prices(70, 200.0),
        }
        df = _multi_df(prices_map)
        aapl = bot_module._get_close_series(df, "AAPL")
        nvda = bot_module._get_close_series(df, "NVDA")

        assert aapl is not None and len(aapl) == 70
        assert nvda is not None and len(nvda) == 70
        assert abs(aapl.iloc[0] - 100.0) < 1e-9
        assert abs(nvda.iloc[0] - 200.0) < 1e-9

    def test_multi_df_missing_ticker_returns_none(self, bot_module):
        """Multi-ticker DataFrame that does not contain the requested ticker."""
        prices_map = {"AAPL": _make_prices(70, 100.0)}
        df = _multi_df(prices_map)
        result = bot_module._get_close_series(df, "MISSING")

        assert result is None

    def test_empty_df_returns_none(self, bot_module):
        """Empty batch DataFrame → returns None for any ticker."""
        result = bot_module._get_close_series(pd.DataFrame(), "AAPL")
        assert result is None

    def test_all_nan_returns_none(self, bot_module):
        """Series of all NaN values should be treated as absent."""
        import numpy as np
        idx = pd.date_range("2024-01-01", periods=10, freq="D")
        df = pd.DataFrame({"Close": [float("nan")] * 10}, index=idx)
        result = bot_module._get_close_series(df, "X")
        # dropna makes the series empty → should return None
        assert result is None


# ---------------------------------------------------------------------------
# B) HISTORY_PERIOD defaulting
# ---------------------------------------------------------------------------

class TestHistoryPeriod:
    """HISTORY_PERIOD should default to '4mo' when not in params.json."""

    def test_default_period_is_4mo(self, bot_module):
        assert bot_module.HISTORY_PERIOD == "4mo"

    def test_period_overridable_from_params(self, monkeypatch, tmp_path):
        """Loading bot.py with a custom HISTORY_PERIOD in params.json."""
        import importlib.util

        # Write a temporary params.json with a custom period
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "params.json").write_text(
            json.dumps({"HISTORY_PERIOD": "3mo"}), encoding="utf-8"
        )
        # targets.json must also be present (just copy the real one)
        real_targets = Path(__file__).resolve().parents[1] / "config" / "targets.json"
        (config_dir / "targets.json").write_bytes(real_targets.read_bytes())

        monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
        monkeypatch.setenv("CHAT_ID", "cid")
        monkeypatch.setenv("BOT_LOG_FILE", str(tmp_path / "bot.log"))
        monkeypatch.chdir(tmp_path)

        project_bot = Path(__file__).resolve().parents[1] / "bot.py"
        spec = importlib.util.spec_from_file_location("bot_custom_period", project_bot)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.HISTORY_PERIOD == "3mo"


# ---------------------------------------------------------------------------
# C) Signal detection unaffected with deterministic synthetic data
# ---------------------------------------------------------------------------

class TestSignalDetectionDeterministic:
    """Verify BUY/SELL crossing detection with fully controlled price series."""

    def _run(self, bot_module, monkeypatch, tmp_path, prices):
        """Run analyze_market() with a single-ticker stub and collect signals."""
        ticker = "SYN"
        bot_module.TARGETS = [{"ticker": ticker, "name": "Synthetic", "market": "US"}]
        bot_module.TICKER_MARKET_MAP = {ticker: "US"}

        positions_path = tmp_path / "positions.json"
        positions_path.write_text("{}", encoding="utf-8")
        bot_module.POSITIONS_FILE = str(positions_path)

        signals = []

        def fake_send(msg):
            if "BUY" in msg or "매수" in msg:
                signals.append("BUY")
            elif "SELL" in msg or "매도" in msg:
                signals.append("SELL")
            return True

        monkeypatch.setattr(
            bot_module,
            "get_market_risk",
            lambda: {"level": "Normal", "score": 50, "summary": "risk"},
        )
        monkeypatch.setattr(bot_module, "get_latest_news", lambda _: "news")
        monkeypatch.setattr(bot_module, "get_ai_comment", lambda **_: "ai")
        monkeypatch.setattr(bot_module, "send_telegram", fake_send)
        monkeypatch.setattr(
            bot_module.yf,
            "download",
            lambda *_a, **_kw: _simple_df(prices),
        )

        bot_module.analyze_market()
        return signals

    def test_buy_signal_on_rsi_oversold_cross(self, bot_module, monkeypatch, tmp_path):
        """Extreme price drop at the last bar should trigger a BUY crossing."""
        # 68 neutral bars then a sudden crash → RSI crosses into oversold
        prices = _make_prices(68) + [100.0, 1.0]
        signals = self._run(bot_module, monkeypatch, tmp_path, prices)
        assert "BUY" in signals

    def test_sell_signal_on_rsi_overbought_cross(self, bot_module, monkeypatch, tmp_path):
        """Extreme spike at the last bar for a *held* position triggers SELL."""
        ticker = "SYN"
        bot_module.TARGETS = [{"ticker": ticker, "name": "Synthetic", "market": "US"}]
        bot_module.TICKER_MARKET_MAP = {ticker: "US"}

        # Pre-populate an open position so the SELL path is exercised
        positions_path = tmp_path / "positions.json"
        initial = {
            ticker: {
                "name": "Synthetic",
                "entry_price": 100.0,
                "highest_price": 100.0,
                "opened_at": "2026-01-01 09:00",
                "market": "US",
            }
        }
        positions_path.write_text(json.dumps(initial), encoding="utf-8")
        bot_module.POSITIONS_FILE = str(positions_path)

        signals = []

        def fake_send(msg):
            if "SELL" in msg or "매도" in msg:
                signals.append("SELL")
            return True

        monkeypatch.setattr(
            bot_module,
            "get_market_risk",
            lambda: {"level": "Normal", "score": 50, "summary": "risk"},
        )
        monkeypatch.setattr(bot_module, "get_latest_news", lambda _: "news")
        monkeypatch.setattr(bot_module, "get_ai_comment", lambda **_: "ai")
        monkeypatch.setattr(bot_module, "send_telegram", fake_send)

        # 68 neutral bars then a massive spike → RSI crosses overbought
        prices = _make_prices(68) + [100.0, 10_000.0]
        monkeypatch.setattr(
            bot_module.yf,
            "download",
            lambda *_a, **_kw: _simple_df(prices),
        )

        bot_module.analyze_market()
        assert "SELL" in signals

    def test_no_signal_on_flat_prices(self, bot_module, monkeypatch, tmp_path):
        """Perfectly flat prices produce no BUY or SELL signal."""
        prices = _make_prices(70)
        signals = self._run(bot_module, monkeypatch, tmp_path, prices)
        assert signals == []

    def test_insufficient_data_skipped(self, bot_module, monkeypatch, tmp_path):
        """Fewer than 60 rows should be silently skipped (no signal, no crash)."""
        prices = _make_prices(30)
        signals = self._run(bot_module, monkeypatch, tmp_path, prices)
        assert signals == []
