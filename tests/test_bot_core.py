def test_escape_telegram_markdown_escapes_special_chars(bot_module):
    raw = "A_[x](y)*`z\\end"
    escaped = bot_module.escape_telegram_markdown(raw)

    for ch in ("_", "*", "[", "]", "(", ")", "`"):
        assert f"\\{ch}" in escaped

    # Backslash should also be escaped.
    assert "\\\\" in escaped


def test_rate_stock_strong_buy_when_signals_align(bot_module):
    rating, score = bot_module.rate_stock(
        curr_price=90.0,
        ma20_val=110.0,
        ma60_val=100.0,
        curr_rsi=20.0,
        curr_upper=120.0,
        curr_lower=80.0,
        market_risk_level="Low",
        market_risk_score=90,
    )

    assert rating == "Strong Buy"
    assert score >= 80


def test_rate_stock_strong_sell_when_signals_worst(bot_module):
    rating, score = bot_module.rate_stock(
        curr_price=120.0,
        ma20_val=90.0,
        ma60_val=100.0,
        curr_rsi=80.0,
        curr_upper=130.0,
        curr_lower=110.0,
        market_risk_level="Extreme",
        market_risk_score=10,
    )

    assert rating == "Strong Sell"
    assert score <= 20
