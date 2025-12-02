import os
import json
import requests
import yfinance as yf
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POSITIONS_FILE = "positions.json"

def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=5)

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
    today = datetime.utcnow().strftime("%Y-%m-%d")

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

    msg = (
        f"☀️ *{today} 모닝 브리핑*\n\n"
        f"🌍 *시장 요약*\n{market_text}\n\n"
        f"💼 *포지션 현황* ({len(positions)}개)\n{pos_block}"
    )

    send_telegram(msg)
    print("Daily briefing sent.")

if __name__ == "__main__":
    daily_briefing()
