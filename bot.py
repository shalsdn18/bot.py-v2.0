import os
import sys
import requests
import traceback
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime

# ==============================
# [Config] GitHub Secrets
# ==============================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ [Error] 환경변수(TELEGRAM_TOKEN / CHAT_ID) 누락")
    sys.exit(1)

# ==============================
# [Target List] 감시할 종목 리스트
# (국장 + 미장 + 배당 + 코인)
# ==============================
TARGETS = [
    # 🇰🇷 KOREA (KR)
    {'ticker': '005930.KS', 'name': '삼성전자', 'market': 'KR'},
    {'ticker': '000660.KS', 'name': 'SK하이닉스', 'market': 'KR'},
    {'ticker': '009150.KS', 'name': '삼성전기', 'market': 'KR'},
    {'ticker': '373220.KS', 'name': 'LG에너지솔루션', 'market': 'KR'},
    {'ticker': '066570.KS', 'name': 'LG전자', 'market': 'KR'},
    {'ticker': '035420.KS', 'name': 'NAVER', 'market': 'KR'},
    {'ticker': '000270.KS', 'name': '기아', 'market': 'KR'},
    {'ticker': '079550.KS', 'name': 'LIG넥스원', 'market': 'KR'},
    {'ticker': '012450.KS', 'name': '한화에어로스페이스', 'market': 'KR'},

    # 🇺🇸 USA (US)
    {'ticker': 'NVDA', 'name': 'NVIDIA', 'market': 'US'},
    {'ticker': 'AMD',  'name': 'AMD', 'market': 'US'},
    {'ticker': 'AVGO', 'name': 'Broadcom', 'market': 'US'},
    {'ticker': 'TSM',  'name': 'TSMC', 'market': 'US'},
    {'ticker': 'MSFT', 'name': 'Microsoft', 'market': 'US'},
    {'ticker': 'AAPL', 'name': 'Apple', 'market': 'US'},
    {'ticker': 'GOOGL', 'name': 'Alphabet', 'market': 'US'},
    {'ticker': 'AMZN', 'name': 'Amazon', 'market': 'US'},
    {'ticker': 'TSLA', 'name': 'Tesla', 'market': 'US'},
    {'ticker': 'SCHD', 'name': 'SCHD ETF', 'market': 'US'},
    {'ticker': 'VYM',  'name': 'VYM ETF', 'market': 'US'},
    {'ticker': 'O',    'name': 'Realty Income', 'market': 'US'},

    # 🪙 CRYPTO
    {'ticker': 'BTC-USD', 'name': 'Bitcoin',  'market': 'COIN'},
    {'ticker': 'ETH-USD', 'name': 'Ethereum', 'market': 'COIN'},
]

# ==========================================
# [Module 1] 뉴스 수집 (News Fetcher)
# ==========================================
def get_latest_news(query: str) -> str:
    try:
        url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        resp = requests.get(url, timeout=5)
        root = ET.fromstring(resp.content)
        news_list = []
        for item in root.findall('./channel/item')[:3]:
            title = item.find('title').text or ''
            link = item.find('link').text or ''
            news_list.append(f"- [{title}]({link})")
        return "\n".join(news_list) if news_list else "(관련 뉴스 없음)"
    except:
        return "(뉴스 수집 실패)"

# ==========================================
# [Module 2] 텔레그램 전송
# ==========================================
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Exception] {e}")

# ==========================================
# [Module 3] 핵심 분석 로직
# ==========================================
def analyze_market():
    print(f"[{datetime.now()}] Market Watch Start...")
    for item in TARGETS:
        ticker = item['ticker']
        name   = item['name']
        try:
            df = yf.download(ticker, period="6mo", progress=False)
            if df.empty or len(df) < 30: continue

            close = df['Close']
            ma20  = close.rolling(window=20).mean()
            std20 = close.rolling(window=20).std()
            upper = ma20 + (std20 * 2)
            lower = ma20 - (std20 * 2)

            curr_price = float(close.iloc[-1])
            curr_lower = float(lower.iloc[-1])
            curr_upper = float(upper.iloc[-1])

            delta = close.diff()
            gain = delta.clip(lower=0).rolling(window=14).mean()
            loss = (-delta.clip(upper=0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, float('nan'))
            rsi = 100 - (100 / (1 + rs))
            curr_rsi = float(rsi.iloc[-1])

            signal = None
            if curr_price < curr_lower or curr_rsi < 30:
                signal = "🚨 *매수(BUY) 신호*"
            elif curr_price > curr_upper or curr_rsi > 70:
                signal = "💰 *매도(SELL) 신호*"

            if signal:
                news_summary = get_latest_news(name)
                msg = (
                    f"{signal}\n"
                    f"--------------------\n"
                    f"📊 종목: {name} ({ticker})\n"
                    f"💵 현재가: {curr_price:,.2f}\n"
                    f"📈 RSI: {curr_rsi:.1f}\n"
                    f"상단밴드: {curr_upper:,.2f}\n"
                    f"하단밴드: {curr_lower:,.2f}\n"
                    f"--------------------\n"
                    f"📰 *관련 뉴스*\n{news_summary}"
                )
                send_telegram(msg)
                print(f">> {name}: Signal Sent.")
            else:
                print(f">> {name}: No Signal.")

        except Exception as e:
            print(f"[Error] {name}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    analyze_market()
