import os
import sys
import json
import requests
import traceback
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime

# Gemini (선택) ----------------------------
try:
    import google.generativeai as genai
except ImportError:
    genai = None
# -----------------------------------------

# ==============================
# [Config] GitHub Secrets
# ==============================
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID         = os.environ.get("CHAT_ID")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY")  # 선택

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ [Error] 환경변수(TELEGRAM_TOKEN / CHAT_ID) 누락")
    sys.exit(1)

# Gemini 설정
if GEMINI_API_KEY and genai is not None:
    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_ENABLED = True
else:
    GEMINI_ENABLED = False

# ==============================
# [Files]
# ==============================
POSITIONS_FILE = "positions.json"

# ==============================
# [Trading Parameters]
# ==============================
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

STOP_LOSS_PCT      = 0.05   # -5% 손절 참고 레벨
TARGET1_PCT        = 0.10   # +10% 1차 목표
TARGET2_PCT        = 0.20   # +20% 2차 목표
TRAIL_START_PCT    = 0.15   # +15%부터 트레일링 감안
TRAILING_STOP_PCT  = 0.05   # 고점 대비 -5% 트레일링 스탑

# ==============================
# [Target List] 실시간 감시 대상
# ==============================
TARGETS = [
    # 🇰🇷 국내 핵심
    {'ticker': '005930.KS', 'name': '삼성전자',                'market': 'KR'},
    {'ticker': '000660.KS', 'name': 'SK하이닉스',              'market': 'KR'},
    {'ticker': '079550.KS', 'name': 'LIG넥스원',               'market': 'KR'},
    {'ticker': '068270.KS', 'name': '셀트리온',                'market': 'KR'},
    {'ticker': '010120.KS', 'name': 'LS ELECTRIC',             'market': 'KR'},
    {'ticker': '570090.KS', 'name': '한투 KIS CD금리투자 ETN', 'market': 'KR'},

    # 🇺🇸 반도체 / AI
    {'ticker': 'NVDA', 'name': 'NVIDIA',   'market': 'US'},
    {'ticker': 'TSM',  'name': 'TSMC',     'market': 'US'},
    {'ticker': 'AMD',  'name': 'AMD',      'market': 'US'},
    {'ticker': 'AVGO', 'name': 'Broadcom', 'market': 'US'},
    {'ticker': 'MU',   'name': 'Micron',   'market': 'US'},

    # 빅테크 / 플랫폼
    {'ticker': 'GOOGL', 'name': 'Alphabet A', 'market': 'US'},
    {'ticker': 'GOOG',  'name': 'Alphabet C', 'market': 'US'},
    {'ticker': 'META',  'name': 'Meta',       'market': 'US'},
    {'ticker': 'MSFT',  'name': 'Microsoft',  'market': 'US'},
    {'ticker': 'AAPL',  'name': 'Apple',      'market': 'US'},
    {'ticker': 'AMZN',  'name': 'Amazon',     'market': 'US'},
    {'ticker': 'TSLA',  'name': 'Tesla',      'market': 'US'},

    # 코인/핀테크/데이터
    {'ticker': 'COIN', 'name': 'Coinbase',         'market': 'US'},
    {'ticker': 'PLTR', 'name': 'Palantir',         'market': 'US'},
    {'ticker': 'AXP',  'name': 'American Express', 'market': 'US'},

    # 배당/방어 ETF
    {'ticker': 'SCHD', 'name': 'SCHD', 'market': 'US'},
    {'ticker': 'GLD',  'name': 'GLD',  'market': 'US'},
]

# ==========================================
# [Module] 포지션 파일 로드/세이브
# ==========================================
def load_positions() -> dict:
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"[Positions Load Error] {e}")
        return {}

def save_positions(data: dict):
    try:
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Positions Save Error] {e}")

# ==========================================
# [Module] 뉴스 수집 (Google News RSS)
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
        for item in root.findall("./channel/item")[:3]:
            title = (item.find("title").text or "").strip()
            link = (item.find("link").text or "").strip()
            if title and link:
                news_list.append(f"- [{title}]({link})")

        if not news_list:
            return "(관련 뉴스 없음)"
        return "\n".join(news_list)
    except Exception as e:
        print(f"[News Error] {query}: {e}")
        return "(뉴스 수집 실패)"

# Gemini용 뉴스 타이틀만 추출 (AI 프롬프트용)
def get_news_titles_for_ai(query: str):
    try:
        url = (
            "https://news.google.com/rss/search?"
            f"q={query}&hl=ko&gl=KR&ceid=KR:ko"
        )
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        titles = []
        for item in root.findall("./channel/item")[:3]:
            title = (item.find("title").text or "").strip()
            if title:
                titles.append(title)
        return titles
    except Exception as e:
        print(f"[NewsTitle Error] {query}: {e}")
        return []

# ==========================================
# [Module] 텔레그램
# ==========================================
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Telegram Error] {e}")

# ==========================================
# [Module] Gemini AI 코멘트
# ==========================================
def get_ai_comment(
    signal_type: str,
    name: str,
    ticker: str,
    roi: float | None,
    curr_rsi: float,
    rating: str,
    score: int,
    risk_summary: str,
    sell_reasons: str | None,
) -> str:
    """
    BUY/SELL 발생 시 간단 3~4줄 코멘트 생성.
    roi 는 SELL일 때만 값, BUY 때는 None.
    """
    if not GEMINI_ENABLED:
        return "(AI 코멘트 비활성화: GEMINI_API_KEY 없음)"

    try:
        news_titles = get_news_titles_for_ai(name)
        titles_text = "\n".join(f"- {t}" for t in news_titles) if news_titles else "(관련 뉴스 제목 없음)"

        base_desc = f"신호 종류: {signal_type}, 종목: {name}({ticker}), RSI={curr_rsi:.1f}, 레이팅={rating}(Score {score}/100)."
        if roi is not None:
            base_desc += f" 현재 포지션 수익률은 {roi:.2f}% 입니다."
        if sell_reasons:
            base_desc += f" 매도 트리거 사유: {sell_reasons}."

        prompt = f"""
        당신은 한국어로 답변하는 주식 애널리스트입니다.
        아래 정보를 바탕으로 간단히 3~4줄 정도로 분석 코멘트를 써주세요.

        [기술 신호/포지션 정보]
        {base_desc}

        [시장 위험도 요약]
        {risk_summary}

        [최근 뉴스 제목 목록]
        {titles_text}

        요구사항:
        - 반드시 한국어로만 답변
        - 형식:
          1) 단기 관점: ...
          2) 중기 관점: ...
          3) 장기 관점: ...
          📌 결론: ... (한 줄 요약)
        - 개별 가격 목표 제시는 하지 말고, 리스크/기회 위주로만 코멘트.
        """

        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()
        return text if text else "(AI 코멘트 생성 실패)"
    except Exception as e:
        return f"(AI 코멘트 오류: {e})"

# ==========================================
# [Module] 시장 위험도 (VIX / UUP / 10Y)
# ==========================================
def get_market_risk():
    try:
        tickers = ["^VIX", "UUP", "^TNX"]
        raw = yf.download(tickers, period="3mo", progress=False)
        if raw.empty:
            raise ValueError("지표 데이터 수신 실패")

        data = raw["Close"].ffill().dropna(how="all")

        vix_series = data["^VIX"].dropna()
        uup_series = data["UUP"].dropna()
        tnx_series = data["^TNX"].dropna()

        if vix_series.empty or uup_series.empty or tnx_series.empty:
            raise ValueError("지표 데이터 부족")

        vix = float(vix_series.iloc[-1])
        uup = float(uup_series.iloc[-1])
        tnx = float(tnx_series.iloc[-1])

        uup_ma20_series = uup_series.rolling(window=20).mean().dropna()
        if uup_ma20_series.empty:
            uup_ma20 = uup
        else:
            uup_ma20 = float(uup_ma20_series.iloc[-1])

        # VIX 레벨
        if vix < 15:
            vol_level = "Low"
        elif vix < 25:
            vol_level = "Normal"
        else:
            vol_level = "High"

        # 금리 레벨
        if tnx < 3.5:
            rate_level = "Low"
        elif tnx < 4.5:
            rate_level = "Normal"
        else:
            rate_level = "High"

        # 달러 레벨
        if uup > uup_ma20 * 1.01:
            dollar_level = "Strong"
        elif uup < uup_ma20 * 0.99:
            dollar_level = "Weak"
        else:
            dollar_level = "Neutral"

        # 스코어링
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
        return {
            "level": "Unknown",
            "score": 50,
            "summary": "시장 위험도: Unknown (지표 수집 실패)"
        }

# ==========================================
# [Module] 레이팅 계산 (Strong Buy ~ Strong Sell)
# ==========================================
def rate_stock(curr_price, ma20_val, ma60_val,
               curr_rsi, curr_upper, curr_lower,
               market_risk_level: str):
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

    # 볼린저 위치
    band_mid = (curr_upper + curr_lower) / 2
    if curr_price < band_mid:
        score += 5
    else:
        score -= 5

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
# [Core] 분석 + 포지션 추적 + AI 코멘트
# ==========================================
def analyze_market():
    print(f"[{datetime.now()}] Market Watch Start...")

    market_risk = get_market_risk()
    risk_level   = market_risk["level"]
    risk_summary = market_risk["summary"]
    print(risk_summary)

    positions = load_positions()
    positions_updated = False

    for item in TARGETS:
        ticker = item["ticker"]
        name   = item["name"]

        try:
            df = yf.download(ticker, period="6mo", progress=False)
            if df.empty or len(df) < 30:
                print(f">> {name} ({ticker}): 데이터 부족, 건너뜀")
                continue

            close = df["Close"]

            # 이동평균 / 볼린저
            ma20 = close.rolling(window=20).mean()
            ma60 = close.rolling(window=60).mean()
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
            rs = gain / loss.replace(0, float("nan"))
            rsi = 100 - (100 / (1 + rs))
            curr_rsi = float(rsi.iloc[-1])
            prev_rsi = float(rsi.iloc[-2])

            # ---- A. 중복 신호 방지: 교차 이벤트만 감지 ----
            buy_now  = (curr_price < curr_lower) or (curr_rsi < RSI_OVERSOLD)
            buy_prev = (prev_price < prev_lower) or (prev_rsi < RSI_OVERSOLD)

            sell_now  = (curr_price > curr_upper) or (curr_rsi > RSI_OVERBOUGHT)
            sell_prev = (prev_price > prev_upper) or (prev_rsi > RSI_OVERBOUGHT)

            event_signal = None  # "BUY" / "SELL" / None
            if buy_now and not buy_prev:
                event_signal = "BUY"
            elif sell_now and not sell_prev:
                event_signal = "SELL"

            # 레이팅
            rating, score = rate_stock(
                curr_price, curr_ma20, curr_ma60,
                curr_rsi, curr_upper, curr_lower,
                risk_level
            )

            # ---- 포지션 여부 확인 ----
            pos = positions.get(ticker)

            # ==================================
            # 1) 보유 중인 종목: 트레일링/SELL 처리
            # ==================================
            if pos:
                entry_price   = pos["entry_price"]
                highest_price = pos.get("highest_price", entry_price)

                # 고점 갱신
                if curr_price > highest_price:
                    highest_price = curr_price
                    pos["highest_price"] = highest_price
                    positions_updated = True

                roi = (curr_price - entry_price) / entry_price * 100
                drop_from_high = (curr_price - highest_price) / highest_price

                trailing_hit  = drop_from_high <= -TRAILING_STOP_PCT
                tech_sell_hit = (event_signal == "SELL")

                sell_reasons = []
                if trailing_hit:
                    sell_reasons.append(
                        f"트레일링 스탑 발동 (고점 대비 {drop_from_high*100:.1f}%)"
                    )
                if tech_sell_hit:
                    sell_reasons.append("기술적 SELL 신호 (밴드 상단/RSI 과매수)")

                if sell_reasons:
                    reason_text = "; ".join(sell_reasons)
                    news_summary = get_latest_news(name)

                    # AI 코멘트
                    ai_comment = get_ai_comment(
                        signal_type="SELL",
                        name=name,
                        ticker=ticker,
                        roi=roi,
                        curr_rsi=curr_rsi,
                        rating=rating,
                        score=score,
                        risk_summary=risk_summary,
                        sell_reasons=reason_text,
                    )

                    msg = (
                        f"💰 *매도(SELL) 실행*\n"
                        f"--------------------\n"
                        f"{risk_summary}\n"
                        f"--------------------\n"
                        f"📊 종목: {name} ({ticker})\n"
                        f"✅ 진입가: {entry_price:,.2f}\n"
                        f"💵 매도가(현재가): {curr_price:,.2f}\n"
                        f"📈 현재 RSI: {curr_rsi:.1f}\n"
                        f"📊 수익률: {roi:.2f}%\n"
                        f"레이팅: {rating} (Score {score}/100)\n"
                        f"사유: {reason_text}\n"
                        f"--------------------\n"
                        f"📰 *관련 뉴스*\n{news_summary}\n"
                        f"--------------------\n"
                        f"🧠 *AI 코멘트*\n{ai_comment}"
                    )
                    send_telegram(msg)
                    del positions[ticker]
                    positions_updated = True
                    print(f">> {name}: Position SOLD. ({reason_text})")
                    continue  # 매도 후 신규 진입 로직 건너뜀

                print(f">> {name}: 보유 중, 수익률 {roi:.2f}% (신규 신호 없음)")
                continue

            # ==================================
            # 2) 미보유 종목: 신규 BUY 진입
            # ==================================
            if not pos and event_signal == "BUY":
                stop_loss   = curr_price * (1 - STOP_LOSS_PCT)
                target1     = curr_price * (1 + TARGET1_PCT)
                target2     = curr_price * (1 + TARGET2_PCT)
                trail_start = curr_price * (1 + TRAIL_START_PCT)

                news_summary = get_latest_news(name)

                ai_comment = get_ai_comment(
                    signal_type="BUY",
                    name=name,
                    ticker=ticker,
                    roi=None,
                    curr_rsi=curr_rsi,
                    rating=rating,
                    score=score,
                    risk_summary=risk_summary,
                    sell_reasons=None,
                )

                msg = (
                    f"🚨 *매수(BUY) 진입*\n"
                    f"--------------------\n"
                    f"{risk_summary}\n"
                    f"--------------------\n"
                    f"📊 종목: {name} ({ticker})\n"
                    f"💵 진입가: {curr_price:,.2f}\n"
                    f"📈 RSI: {curr_rsi:.1f}\n"
                    f"레이팅: {rating} (Score {score}/100)\n"
                    f"--------------------\n"
                    f"🎯 리스크/목표 레벨(현재 진입 기준)\n"
                    f"- 손절가(-{int(STOP_LOSS_PCT*100)}%): {stop_loss:,.2f}\n"
                    f"- 1차 목표가(+{int(TARGET1_PCT*100)}%): {target1:,.2f}\n"
                    f"- 2차 목표가(+{int(TARGET2_PCT*100)}%): {target2:,.2f}\n"
                    f"- 트레일링 시작 구간(약 +{int(TRAIL_START_PCT*100)}%): "
                    f"{trail_start:,.2f}\n"
                    f"--------------------\n"
                    f"📰 *관련 뉴스*\n{news_summary}\n"
                    f"--------------------\n"
                    f"🧠 *AI 코멘트*\n{ai_comment}"
                )
                send_telegram(msg)

                positions[ticker] = {
                    "name": name,
                    "entry_price": curr_price,
                    "highest_price": curr_price,
                    "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                positions_updated = True
                print(f">> {name}: Position OPENED.")
            else:
                print(f">> {name}: No New Signal / No Position.")

        except Exception as e:
            print(f"[Error] {name} ({ticker}): {e}")
            traceback.print_exc()

    if positions_updated:
        save_positions(positions)
        print(">> positions.json updated.")

# ==========================================
# main
# ==========================================
if __name__ == "__main__":
    analyze_market()
