import os
import json
import logging
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POSITIONS_FILE = "positions.json"
LOG_FILE = os.environ.get("BOT_DAILY_LOG_FILE", "daily_report.log")

logger = logging.getLogger("daily_report")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=500_000,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

TELEGRAM_SEND_STATS = {
    "success": 0,
    "fallback_success": 0,
    "failed": 0,
}


def escape_telegram_markdown(text: str) -> str:
    if text is None:
        return ""
    escaped = str(text).replace("\\", "\\\\")
    for ch in ("_", "*", "[", "]", "(", ")", "`"):
        escaped = escaped.replace(ch, f"\\{ch}")
    return escaped

def send_telegram(msg: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        TELEGRAM_SEND_STATS["success"] += 1
        logger.info("Daily Telegram message sent (markdown)")
        return True
    except Exception as e:
        print(f"[Telegram Markdown Error] {e}")
        logger.warning(f"Daily Telegram markdown send failed: {e}")
        try:
            fallback_payload = {"chat_id": CHAT_ID, "text": msg}
            fallback_resp = requests.post(url, json=fallback_payload, timeout=5)
            fallback_resp.raise_for_status()
            TELEGRAM_SEND_STATS["fallback_success"] += 1
            print("[Telegram] Fallback plain text 전송 성공")
            logger.info("Daily Telegram message sent via plain text fallback")
            return True
        except Exception as fallback_e:
            TELEGRAM_SEND_STATS["failed"] += 1
            print(f"[Telegram Error] {fallback_e}")
            logger.error(f"Daily Telegram send failed completely: {fallback_e}")
            return False

def get_market_overview():
    indices = {
        "S&P500": "^GSPC",
        "KOSPI": "^KS11",
        "USD/KRW": "KRW=X"
    }
    lines = []
    for name, ticker in indices.items():
        try:
            df = yf.download(ticker, period="5d", progress=False)
            close = df["Close"].iloc[-1]
            prev  = df["Close"].iloc[-2]
            change = (close - prev) / prev * 100
            lines.append(f"- {name}: {close:,.2f} ({change:+.2f}%)")
        except Exception as e:
            lines.append(f"- {name}: 데이터 오류 ({e})")
    return "\n".join(lines)

def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return {}
    with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def daily_briefing():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).strftime("%Y-%m-%d")
    logger.info("Daily briefing started")

    # 1. 시장 요약
    market_text = get_market_overview()

    # 2. 포지션 현황
    positions = load_positions()
    pos_lines = []
    for ticker, info in positions.items():
        name = info.get("name", ticker)
        entry = info.get("entry_price", None)
        try:
            price = yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1]
            if entry:
                roi = (price - entry) / entry * 100
                pos_lines.append(
                    f"- {name} ({ticker}): 현재가 {price:,.2f}, 수익률 {roi:+.2f}%"
                )
            else:
                pos_lines.append(
                    f"- {name} ({ticker}): 현재가 {price:,.2f}"
                )
        except Exception:
            pos_lines.append(f"- {name} ({ticker}): 가격 확인 실패")

    pos_block = "\n".join(pos_lines) if pos_lines else "보유 종목 없음"

    today_md = escape_telegram_markdown(today)
    market_text_md = escape_telegram_markdown(market_text)
    pos_block_md = escape_telegram_markdown(pos_block)

    msg = (
        f"☀️ *{today_md} 모닝 브리핑*\n\n"
        f"🌍 *시장 요약*\n{market_text_md}\n\n"
        f"💼 *포지션 현황* ({len(positions)}개)\n{pos_block_md}"
    )

    send_telegram(msg)
    logger.info(
        "Daily Telegram stats: success=%d, fallback_success=%d, failed=%d",
        TELEGRAM_SEND_STATS["success"],
        TELEGRAM_SEND_STATS["fallback_success"],
        TELEGRAM_SEND_STATS["failed"],
    )
    print("Daily briefing sent.")

if __name__ == "__main__":
    daily_briefing()
