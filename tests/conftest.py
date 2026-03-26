import importlib.util
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bot_module(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "test_token")
    monkeypatch.setenv("CHAT_ID", "test_chat")
    monkeypatch.setenv("BOT_LOG_FILE", str(tmp_path / "bot.log"))
    monkeypatch.chdir(PROJECT_DIR)
    return _load_module(PROJECT_DIR / "bot.py", "bot_under_test")


@pytest.fixture
def daily_module(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "test_token")
    monkeypatch.setenv("CHAT_ID", "test_chat")
    monkeypatch.setenv("BOT_DAILY_LOG_FILE", str(tmp_path / "daily.log"))
    monkeypatch.chdir(PROJECT_DIR)
    return _load_module(PROJECT_DIR / "daily_report.py", "daily_under_test")
