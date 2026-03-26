def test_daily_briefing_prints_failure_when_send_fails(daily_module, monkeypatch, capsys):
    monkeypatch.setattr(daily_module, "get_market_overview", lambda: "overview")
    monkeypatch.setattr(daily_module, "load_positions", lambda: {})
    monkeypatch.setattr(daily_module, "send_telegram", lambda _msg: False)

    daily_module.daily_briefing()

    out = capsys.readouterr().out.lower()
    assert "failed to send" in out


def test_daily_briefing_prints_success_when_send_succeeds(daily_module, monkeypatch, capsys):
    monkeypatch.setattr(daily_module, "get_market_overview", lambda: "overview")
    monkeypatch.setattr(daily_module, "load_positions", lambda: {})
    monkeypatch.setattr(daily_module, "send_telegram", lambda _msg: True)

    daily_module.daily_briefing()

    out = capsys.readouterr().out.lower()
    assert "daily briefing sent" in out
