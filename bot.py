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
# [Trading Parameters]
# ==============================
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

STOP_LOSS_PCT     = 0.05   # -5%
TARGET1_PCT       = 0.10   # +10%
TARGET2_PCT       = 0.20   # +20%
TRAIL_START_PCT   = 0.15   # +15% 이상에서 트레일링 시작 가정
TRAIL_GAP_PCT     = 0.03   # 고점 대비 -3% 하락 시 트레일링 스탑

# ==============================
# [Target List] 감시할 종목 리스트
# ==============================
TARGETS = [
    # KOREA
    {'ticker': '005930.KS', 'name': '삼성전자',         'market': 'KR'},
    {'ticker': '000660.KS', 'name': 'SK하이닉스',       'market': 'KR'},
    {'ticker': '009150.KS', 'name': '삼성전기',         'market': 'KR'},
    {'ticker': '373220.KS', 'name': 'LG에너지솔루션',   'market': 'KR'},
    {'ticker': '066570.KS', 'name': 'LG전자',           'market': 'KR'},
    {'ticker': '035420.KS', 'name': 'NAVER',            'market': 'KR'},
    {'ticker': '000270.KS', 'name': '기아',             'market': 'KR'},
    {'ticker': '079550.KS', 'name': 'LIG넥스원',        'market': 'KR'},
    {'ticker': '012450.KS', 'name': '한화에어로스페이스','market': 'KR'},
    # 선택 감시
    {'ticker': '011200.KS', 'name': 'HMM',              'market': 'KR'},
    {'ticker': '034220.KS', 'name': 'LG디스플레이',     'market': 'KR'},

    # USA – AI/반도체/빅테크
    {'ticker': 'NVDA', 'name': 'NVIDIA',    'market': 'US'},
    {'ticker': 'AMD',  'name': 'AMD',       'market': 'US'},
    {'ticker': 'AVGO', 'name': 'Broadcom',  'market': 'US'},
    {'ticker': 'TSM',  'name': 'TSMC',      'market': 'US'},
    {'ticker': 'MSFT', 'name': 'Microsoft', 'market': 'US'},
    {'ticker': 'AAPL', 'name': 'Apple',     'market': 'US'},
    {'ticker': 'GOOGL','name': 'Alphabet',  'market': 'US'},
    {'ticker': 'AMZN', 'name': 'Amazon',    'market': 'US'},
    {'ticker': 'TSLA', 'name': 'Tesla',     'market': 'US'},

    # Dividend / Cash-flow
    {'ticker': 'SCHD', 'name': 'SCHD ETF',         'market': 'US'},
    {'ticker': 'VYM',  'name': 'VYM ETF',          'market': 'US'},
    {'ticker': 'O',    'name': 'Realty Income',    'market': 'US'},

    # Crypto (시장 컨디션 관찰용)
    {'ticker': 'BTC-USD', 'name': 'Bitcoin',  'market': 'COIN'},
    {'ticker': 'ETH-USD', 'name': 'Ethereum', 'market': 'COIN'},
]

# ==========================================
# [Module 1] 뉴스 수집
# ==========================================
def get_latest_news(query: str) -> str:
    try:
        url = (
            "https://news.google.com/rss/search?"
            f"q={query}&hl=ko&gl=KR&ceid=KR:ko"
        )
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        news_list = []
        for item in root.findall('./channel/item')[:3]:
            title = (item.find('title').text or '').strip()
            link  = (item.find('link').text or '').strip()
            if title and link:
                news_list.append(f"- [{title}]({link})")

        if not news_list:
            return "(관련 뉴스 없음)"
        return "\n".join(news_list)

    except Exception as e:
        print(f"[News Error] {query}: {e}")
        return "(뉴스 수집 실패)"

# ==========================================
# [Module 2] 텔레그램 전송
# ==========================================
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            'chat_id': CHAT_ID,
            'text': msg,
            'parse_mode': 'Markdown'
        }
        resp = requests.post(url, json=payload, timeout=5)
        if not resp.ok:
            print(f"[Telegram Error] {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[Telegram Exception] {e}")

# ==========================================
# [Module 3] 시장 지표(VIX/달러/금리) 분석
# ==========================================
def get_market_risk():
    """
    VIX, 달러(UUP), 미10년(^TNX)를 이용해
    시장 위험 레벨을 Low/Normal/High/Extreme로 분류
    """
    try:
        tickers = ['^VIX', 'UUP', '^TNX']
        data = yf.download(tickers, period="1mo", progress=False)['Close']

        vix  = float(data['^VIX'].iloc[-1])
        uup  = float(data['UUP'].iloc[-1])
        tnx  = float(data['^TNX'].iloc[-1])

        uup_ma20 = float(data['UUP'].rolling(window=20).mean().iloc[-1])

        # VIX 레벨
        if vix < 15:
            vol_level = "Low"
        elif vix < 25:
            vol_level = "Normal"
        else:
            vol_level = "High"

        # 금리 레벨 (대략적인 구간)
        if tnx < 3.5:
            rate_level = "Low"
        elif tnx < 4.5:
            rate_level = "Normal"
        else:
            rate_level = "High"

        # 달러 강도 (UUP vs 20일선)
        if uup > uup_ma20 * 1.01:
            dollar_level = "Strong"
        elif uup < uup_ma20 * 0.99:
            dollar_level = "Weak"
        else:
            dollar_level = "Neutral"

        # 위험 점수화
        score = 50
        if vol_level == "Low":
            score += 5
        elif vol_level == "High":
            score -= 10

        if rate_level == "Low":
            score += 5
        elif rate_level == "High":
            score -= 10

        if dollar_level == "Strong":
            score -= 5
        elif dollar_level == "Weak":
            score += 5

        score = max(0, min(100, score))

        if score >= 70:
            level = "Low"
        elif score >= 40:
            level = "Normal"
        elif score >= 20:
            level = "High"
        else:
            level = "Extreme"

        summary = (
            f"시장 위험도: {level} (Score {score}/100)\n"
            f"VIX: {vix:.1f} ({vol_level}), "
            f"10Y: {tnx:.2f}% ({rate_level}), "
            f"달러(UUP): {uup:.2f} ({dollar_level})"
        )

        return {"level": level, "score": score, "summary": summary}

    except Exception as e:
        print(f"[Market Risk Error] {e}")
        return {"level": "Unknown", "score": 50,
                "summary": "시장 위험도: Unknown (지표 수집 실패)"}

# ==========================================
# [Module 4] 레이팅 계산
# ==========================================
def rate_stock(curr_price, ma20_val, ma60_val,
               curr_rsi, curr_upper, curr_lower,
               market_risk_level: str):
    """
    기술 + 시장위험 기반 점수(0~100)와 레이팅 문자열 반환
    """
    score = 50

    # RSI
    if curr_rsi < 30:
        score += 15
    elif curr_rsi < 40:
        score += 5
    elif curr_rsi > 70:
        score -= 15
    elif curr_rsi > 60:
        score -= 5

    # 추세 (20일 vs 60일)
    if ma20_val > ma60_val:
        score += 10
    else:
        score -= 10

    # 20일선 기울기 (최근 5일)
    slope = ma20_val  # placeholder, 실제로는 최근 값 차이
    # 위에서 ma20_val만 쓰고 있어 slope는 단순화
    # 추세 방향만 추가적인 점수로 고려하려면
    # analyze 함수 안에서 5일 차이로 계산해 전달해도 됨

    # 볼린저 내 위치
    band_mid = (curr_upper + curr_lower) / 2
    if curr_price < band_mid:
        score += 5   # 상대적 저점
    else:
        score -= 5   # 상대적 고점

    # 시장 위험도
    if market_risk_level == "Low":
        score += 5
    elif market_risk_level == "High":
        score -= 10
    elif market_risk_level == "Extreme":
        score -= 20

    score = max(0, min(100, score))

    if score >= 80:
        rating = "Strong Buy"
    elif score >= 60:
        rating = "Buy"
    elif score >= 40:
        rating = "Neutral"
    elif score >= 20:
        rating = "Sell"
    else:
        rating = "Strong Sell"

    return rating, score

# ==========================================
# [Module 5] 핵심 분석 로직
# ==========================================
def analyze_market():
    print(f"[{datetime.now()}] Market Watch Start...")

    market_risk = get_market_risk()
    risk_level   = market_risk["level"]
    risk_summary = market_risk["summary"]

    print(risk_summary)

    for item in TARGETS:
        ticker = item['ticker']
        name   = item['name']

        try:
            df = yf.download(ticker, period="6mo", progress=False)
            if df.empty or len(df) < 30:
                print(f">> {name} ({ticker}): 데이터 부족, 건너뜀")
                continue

            close = df['Close']

            # 이동평균
            ma20 = close.rolling(window=20).mean()
            ma60 = close.rolling(window=60).mean()

            # 볼린저
            std20 = close.rolling(window=20).std()
            upper = ma20 + (std20 * 2)
            lower = ma20 - (std20 * 2)

            curr_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])

            curr_ma20  = float(ma20.iloc[-1])
            curr_ma60  = float(ma60.iloc[-1])
            curr_upper = float(upper.iloc[-1])
            curr_lower = float(lower.iloc[-1])
            prev_upper = float(upper.iloc[-2])
            prev_lower = float(lower.iloc[-2])

            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(window=14).mean()
            loss = (-delta.clip(upper=0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, float('nan'))
            rsi = 100 - (100 / (1 + rs))
            curr_rsi = float(rsi.iloc[-1])
            prev_rsi = float(rsi.iloc[-2])

            # --------------------------
            # A. 중복 신호 방지 로직
            # --------------------------
            buy_now  = (curr_price < curr_lower) or (curr_rsi < RSI_OVERSOLD)
            buy_prev = (prev_price < prev_lower) or (prev_rsi < RSI_OVERSOLD)

            sell_now  = (curr_price > curr_upper) or (curr_rsi > RSI_OVERBOUGHT)
            sell_prev = (prev_price > prev_upper) or (prev_rsi > RSI_OVERBOUGHT)

            signal = None
            signal_type = None

            if buy_now and not buy_prev:
                signal = "🚨 *매수(BUY) 신호*"
                signal_type = "BUY"
            elif sell_now and not sell_prev:
                signal = "💰 *매도(SELL) 신호*"
                signal_type = "SELL"

            if not signal:
                print(f">> {name}: No New Signal.")
                continue

            # --------------------------
            # B. 목표가 / 손절 / 트레일링 레벨 계산
            # (가상의 신규 진입 기준 참고용)
            # --------------------------
            stop_loss = curr_price * (1 - STOP_LOSS_PCT)
            target1   = curr_price * (1 + TARGET1_PCT)
            target2   = curr_price * (1 + TARGET2_PCT)
            trail_start = curr_price * (1 + TRAIL_START_PCT)

            # --------------------------
            # D. 종목 레이팅 계산
            # --------------------------
            rating, score = rate_stock(
                curr_price, curr_ma20, curr_ma60,
                curr_rsi, curr_upper, curr_lower,
                risk_level
            )

            # 뉴스
            news_summary = get_latest_news(name)

            msg = (
                f"{signal}\n"
                f"--------------------\n"
                f"{risk_summary}\n"
                f"--------------------\n"
                f"📊 종목: {name} ({ticker})\n"
                f"💵 현재가: {curr_price:,.2f}\n"
                f"📈 RSI: {curr_rsi:.1f}\n"
                f"상단밴드: {curr_upper:,.2f}\n"
                f"하단밴드: {curr_lower:,.2f}\n"
                f"레이팅: {rating} (Score {score}/100)\n"
                f"--------------------\n"
                f"🎯 리스크/목표 레벨(가상의 신규 진입 기준)\n"
                f"- 손절가(-{int(STOP_LOSS_PCT*100)}%): {stop_loss:,.2f}\n"
                f"- 1차 목표가(+{int(TARGET1_PCT*100)}%): {target1:,.2f}\n"
                f"- 2차 목표가(+{int(TARGET2_PCT*100)}%): {target2:,.2f}\n"
                f"- 트레일링 시작 구간(약 +{int(TRAIL_START_PCT*100)}%): "
                f"{trail_start:,.2f}\n"
                f"--------------------\n"
                f"📰 *관련 뉴스*\n{news_summary}"
            )

            send_telegram(msg)
            print(f">> {name}: Signal Sent ({signal_type}).")

        except Exception as e:
            print(f"[Error] {name} ({ticker}): {e}")
            traceback.print_exc()

if __name__ == "__main__":
    analyze_market()

