from types import SimpleNamespace


class GeminiError(Exception):
    def __init__(self, code, message="gemini error"):
        super().__init__(message)
        self.code = code


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate_content(self, *, model, contents):
        self.calls.append((model, contents))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


def _comment(bot_module, monkeypatch, responses, sleep=None):
    client = FakeClient(responses)
    monkeypatch.setattr(bot_module, "GEMINI_CLIENT", client)
    monkeypatch.setattr(bot_module, "GEMINI_MODEL", "confirmed-model-id")
    if sleep is not None:
        monkeypatch.setattr(bot_module.time, "sleep", sleep)
    return bot_module.generate_ai_comment("signal prompt"), client


def test_missing_api_key_disables_only_gemini(bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "GEMINI_CLIENT", None)

    assert bot_module.generate_ai_comment("prompt") == "(AI 코멘트 비활성화)"
    assert bot_module.rate_stock(
        90.0, 110.0, 100.0, 20.0, 120.0, 80.0, "Low", 90
    )[0] == "Strong Buy"


def test_gemini_success_uses_configured_model(bot_module, monkeypatch):
    comment, client = _comment(
        bot_module,
        monkeypatch,
        [SimpleNamespace(text="  한국어 코멘트  ")],
    )

    assert comment == "한국어 코멘트"
    assert client.models.calls == [("confirmed-model-id", "signal prompt")]


def test_gemini_429_retries_with_bounded_backoff_then_falls_back(
    bot_module, monkeypatch
):
    delays = []
    comment, client = _comment(
        bot_module,
        monkeypatch,
        [GeminiError(429, "RESOURCE_EXHAUSTED")] * 3,
        delays.append,
    )

    assert comment == "(할당량 초과: 잠시 후 재시도)"
    assert len(client.models.calls) == 3
    assert delays == [1.0, 2.0]


def test_gemini_timeout_falls_back_after_bounded_retries(bot_module, monkeypatch):
    delays = []
    comment, client = _comment(
        bot_module,
        monkeypatch,
        [TimeoutError("request timed out")] * 3,
        delays.append,
    )

    assert comment == "(AI 코멘트 생성 실패)"
    assert len(client.models.calls) == 3
    assert delays == [1.0, 2.0]


def test_gemini_5xx_retries_and_falls_back(bot_module, monkeypatch):
    delays = []
    comment, client = _comment(
        bot_module,
        monkeypatch,
        [GeminiError(503)] * 3,
        delays.append,
    )

    assert comment == "(AI 코멘트 생성 실패)"
    assert len(client.models.calls) == 3
    assert delays == [1.0, 2.0]


def test_gemini_auth_failure_does_not_retry(bot_module, monkeypatch):
    delays = []
    comment, client = _comment(
        bot_module,
        monkeypatch,
        [GeminiError(401, "UNAUTHENTICATED")],
        delays.append,
    )

    assert comment == "(AI 코멘트 생성 실패)"
    assert len(client.models.calls) == 1
    assert delays == []


def test_gemini_empty_response_falls_back_without_retry(bot_module, monkeypatch):
    delays = []
    comment, client = _comment(
        bot_module,
        monkeypatch,
        [SimpleNamespace(text="   ")],
        delays.append,
    )

    assert comment == "(AI 응답 내용 없음)"
    assert len(client.models.calls) == 1
    assert delays == []


def test_gemini_failure_does_not_change_position_state_or_block_core_message(
    bot_module, monkeypatch
):
    positions = {"005930.KS": {"entry_price": 100.0, "target1_hit": False}}
    monkeypatch.setattr(bot_module, "GEMINI_CLIENT", FakeClient([GeminiError(403)]))
    monkeypatch.setattr(bot_module, "GEMINI_MODEL", "confirmed-model-id")
    monkeypatch.setattr(bot_module, "get_news_titles_for_ai", lambda _name: [])

    comment = bot_module.get_ai_comment(
        signal_type="SELL",
        name="삼성전자",
        ticker="005930.KS",
        roi=-2.0,
        curr_rsi=70.0,
        rating="Sell",
        score=30,
        risk_summary="Normal",
        sell_reasons="손절가 도달",
    )

    assert comment == "(AI 코멘트 생성 실패)"
    assert positions == {"005930.KS": {"entry_price": 100.0, "target1_hit": False}}
    assert "매도(SELL) 실행" in f"매도(SELL) 실행\n{comment}"
