import os
import sys
import json
import requests
import traceback
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

  # Gemini (google-genai) -------------------------
try:
    from google import genai
    GEMINI_CLIENT = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
except Exception as e:
    GEMINI_CLIENT = None


# ==============================
# [Config] GitHub Secrets
# ==============================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")  # 선택

# ==============================
# [Config JSON] targets / params
# ==============================
def load_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ [Config Error] {path} 로드 실패: {e}")
        return default if default is not None else {}

TARGETS = load_json("config/targets.json", default=[])
P = load_json("config/params.json", default={})

if not TARGETS:
    print("❌ [Error] config/targets.json이 비어있거나 로드 실패")
    sys.exit(1)

TICKER_MARKET_MAP = {t["ticker"]: t.get("market", "UNKNOWN") for t in TARGETS}

# ==============================
# [Trading Parameters] (JSON 우선)
# ==============================
RSI_OVERSOLD = int(P.get("RSI_OVERSOLD", 30))
RSI_OVERBOUGHT = int(P.get("RSI_OVERBOUGHT", 70))

STOP_LOSS_PCT = float(P.get("STOP_LOSS_PCT", 0.05))
TARGET1_PCT = float(P.get("TARGET1_PCT", 0.10))
TARGET2_PCT = float(P.get("TARGET2_PCT", 0.20))
TRAIL_START_PCT = float(P.get("TRAIL_START_PCT", 0.15))
TRAILING_STOP_PCT = float(P.get("TRAILING_STOP_PCT", 0.05))

MARKET_SCORE_BLOCK_BUY = int(P.get("MARKET_SCORE_BLOCK_BUY", 30))
MARKET_SCORE_STRONG_BOOST = int(P.get("MARKET_SCORE_STRONG_BOOST", 80))

MAX_KR_POSITIONS = int(P.get("MAX_KR_POSITIONS", 4))


if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ [Error] 환경변수(TELEGRAM_TOKEN / CHAT_ID) 누락")
    sys.exit(1)



# ==============================
# [Files]
# ==============================
POSITIONS_FILE = "positions.json"

# ==============================
# [Trading Parameters]
# ==============================
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

STOP_LOSS_PCT = 0.05   # -5% 손절 참고 레벨
TARGET1_PCT = 0.10     # +10% 1차 목표
TARGET2_PCT = 0.20     # +20% 2차 목표
TRAIL_START_PCT = 0.15 # +15%부터 트레일링 감안
TRAILING_STOP_PCT = 0.05  # 고점 대비 -5% 트레일링 스탑

# 시장 과열/공포 필터 (확장 옵션 A)
MARKET_SCORE_BLOCK_BUY = 30   # 이하면 신규 매수 차단
MARKET_SCORE_STRONG_BOOST = 80  # 이상이면 레이팅 추가 가점

# 국장 포지션 최대 개수
MAX_KR_POSITIONS = 4




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


def get_position_market(pos_ticker: str, pos_data: dict) -> str:
    if "market" in pos_data:
        return pos_data["market"]
    return TICKER_MARKET_MAP.get(pos_ticker, "UNKNOWN")


def count_positions_by_market(positions: dict, market: str) -> int:
    return sum(1 for t, p in positions.items() if get_position_market(t, p) == market)


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


def get_ai_comment(
    signal_type: str,
    name: str,
    ticker: str,
    roi: Optional[float],
    curr_rsi: float,
    rating: str,
    score: int,
    risk_summary: str,
    sell_reasons: Optional[str],
) -> str:
    if GEMINI_CLIENT is None:
        return "(AI 코멘트 비활성화: GEMINI_CLIENT 초기화 실패 / API 키 확인)"

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
        """.strip()

        return generate_ai_comment(prompt)
    except Exception as e:
        return f"(AI 코멘트 오류: {e})"


def generate_ai_comment(prompt: str) -> str:
    try:
        if GEMINI_CLIENT is None:
            return "(GEMINI_CLIENT 초기화 실패)"

        # 🔍 2026년 가용 모델 리스트 중 최적의 모델로 교체
        # 'models/'를 포함해야 하는지 여부는 라이브러리 버전에 따라 다르지만, 
        # 리스트에 뜬 그대로 'models/gemini-2.5-flash'를 넣는 것이 가장 안전합니다.
        model_name = os.environ.get("GEMINI_MODEL", "models/gemini-2.5-flash")

        resp = GEMINI_CLIENT.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return resp.text
    except Exception as e:
        return f"(AI 코멘트 생성 실패: {e})"



def get_market_risk():
    try:
        tickers = ["^VIX", "UUP", "^TNX"]
        raw = yf.download(tickers, period="3mo", progress=False, auto_adjust=False)
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
        uup_ma20 = float(uup_ma20_series.iloc[-1]) if not uup_ma20_series.empty else uup

        if vix < 15:
            vol_level = "Low"
        elif vix < 25:
            vol_level = "Normal"
        else:
            vol_level = "High"

        if tnx < 3.5:
            rate_level = "Low"
        elif tnx < 4.5:
            rate_level = "Normal"
        else:
            rate_level = "High"

        if uup > uup_ma20 * 1.01:
            dollar_level = "Strong"
        elif uup < uup_ma20 * 0.99:
            dollar_level = "Weak"
        else:
            dollar_level = "Neutral"

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
        return {"level": "Unknown", "score": 50, "summary": "시장 위험도: Unknown (지표 수집 실패)"}


def rate_stock(
    curr_price: float,
    ma20_val: float,
    ma60_val: float,
    curr_rsi: float,
    curr_upper: float,
    curr_lower: float,
    market_risk_level: str,
    market_risk_score: int,
):
    score = 50

    if curr_rsi < 30:
        score += 15
    elif curr_rsi < 40:
        score += 5
    elif curr_rsi > 70:
        score -= 15
    elif curr_rsi > 60:
        score -= 5

    if ma20_val > ma60_val:
        score += 10
    else:
        score -= 10

    band_mid = (curr_upper + curr_lower) / 2
    if curr_price < band_mid:
        score += 5
    else:
        score -= 5

    if market_risk_level == "Low":
        score += 5
        if market_risk_score >= MARKET_SCORE_STRONG_BOOST:
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


def analyze_market():
    print(f"[{datetime.now()}] Market Watch Start...")

    market_risk = get_market_risk()
    risk_level = market_risk["level"]
    risk_score = market_risk["score"]
    risk_summary = market_risk["summary"]
    print(risk_summary)

    positions = load_positions()
    positions_updated = False

    def _scalar(x) -> float:
        return float(x.item()) if hasattr(x, "item") else float(x)

    for item in TARGETS:
        ticker = item["ticker"]
        name = item["name"]
        market = item["market"]

        try:
            df = yf.download(ticker, period="6mo", progress=False, auto_adjust=False)
            if df.empty or len(df) < 60:
                print(f">> {name} ({ticker}): 데이터 부족, 건너뜀")
                continue

            close = df["Close"]
            # yfinance가 DataFrame으로 주는 케이스(멀티컬럼) 대응
            if hasattr(close, "columns"):
                close = close[ticker]

            # RSI 먼저 계산
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(window=14).mean()
            loss = (-delta.clip(upper=0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi = 100 - (100 / (1 + rs))

            # 이동평균 / 볼린저
            ma20 = close.rolling(window=20).mean()
            ma60 = close.rolling(window=60).mean()
            std20 = close.rolling(window=20).std()
            upper = ma20 + (std20 * 2)
            lower = ma20 - (std20 * 2)

            # 최신값 스칼라 변환
            curr_price = _scalar(close.iloc[-1])
            prev_price = _scalar(close.iloc[-2])

            curr_ma20 = _scalar(ma20.iloc[-1])
            curr_ma60 = _scalar(ma60.iloc[-1])

            curr_upper = _scalar(upper.iloc[-1])
            curr_lower = _scalar(lower.iloc[-1])
            prev_upper = _scalar(upper.iloc[-2])
            prev_lower = _scalar(lower.iloc[-2])

            curr_rsi = _scalar(rsi.iloc[-1])
            prev_rsi = _scalar(rsi.iloc[-2])

            # ---- A. 중복 신호 방지: 교차 이벤트만 감지 ----
            buy_now = (curr_price < curr_lower) or (curr_rsi < RSI_OVERSOLD)
            buy_prev = (prev_price < prev_lower) or (prev_rsi < RSI_OVERSOLD)

            sell_now = (curr_price > curr_upper) or (curr_rsi > RSI_OVERBOUGHT)
            sell_prev = (prev_price > prev_upper) or (prev_rsi > RSI_OVERBOUGHT)

            event_signal = None
            if buy_now and not buy_prev:
                event_signal = "BUY"
            elif sell_now and not sell_prev:
                event_signal = "SELL"

            rating, score = rate_stock(
                curr_price, curr_ma20, curr_ma60,
                curr_rsi, curr_upper, curr_lower,
                risk_level, risk_score
            )

            pos = positions.get(ticker)

            # 1) 보유 중: SELL/트레일링 처리
            if pos:
                entry_price = pos["entry_price"]
                highest_price = pos.get("highest_price", entry_price)

                if curr_price > highest_price:
                    highest_price = curr_price
                    pos["highest_price"] = highest_price
                    pos["market"] = market
                    positions_updated = True

                roi = (curr_price - entry_price) / entry_price * 100
                drop_from_high = (curr_price - highest_price) / highest_price

                trailing_hit = drop_from_high <= -TRAILING_STOP_PCT
                tech_sell_hit = (event_signal == "SELL")

                sell_reasons = []
                if trailing_hit:
                    sell_reasons.append(f"트레일링 스탑 발동 (고점 대비 {drop_from_high*100:.1f}%)")
                if tech_sell_hit:
                    sell_reasons.append("기술적 SELL 신호 (밴드 상단/RSI 과매수)")

                if sell_reasons:
                    reason_text = "; ".join(sell_reasons)
                    news_summary = get_latest_news(name)

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
                    continue

                print(f">> {name}: 보유 중, 수익률 {roi:.2f}% (신규 신호 없음)")
                continue

            # 2) 미보유: 신규 BUY
            if event_signal == "BUY":
                if risk_score <= MARKET_SCORE_BLOCK_BUY:
                    print(f">> {name}: BUY 신호지만 시장 점수 {risk_score} <= {MARKET_SCORE_BLOCK_BUY}, 매수 차단.")
                    continue

                if market == "KR":
                    kr_open = count_positions_by_market(positions, "KR")
                    if kr_open >= MAX_KR_POSITIONS:
                        print(f">> {name}: 국장 포지션 {kr_open}개, MAX={MAX_KR_POSITIONS} → 매수 스킵.")
                        continue

                stop_loss = curr_price * (1 - STOP_LOSS_PCT)
                target1 = curr_price * (1 + TARGET1_PCT)
                target2 = curr_price * (1 + TARGET2_PCT)
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
                    f"- 트레일링 시작 구간(약 +{int(TRAIL_START_PCT*100)}%): {trail_start:,.2f}\n"
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
                    "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "market": market,
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


if __name__ == "__main__":
    analyze_market()
