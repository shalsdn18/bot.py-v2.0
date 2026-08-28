import os
import sys
import json
import logging
import time
import requests
import traceback
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional, Callable, TypeVar, Any

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
SPRING_WEBHOOK_URL = os.environ.get("SPRING_WEBHOOK_URL", "http://localhost:8080/api/signals/webhook")

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
HISTORY_PERIOD = str(P.get("HISTORY_PERIOD", "4mo"))


if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ [Error] 환경변수(TELEGRAM_TOKEN / CHAT_ID) 누락")
    sys.exit(1)



# ==============================
# [Files]
# ==============================
POSITIONS_FILE = "positions.json"
LOG_FILE = os.environ.get("BOT_LOG_FILE", "bot.log")

logger = logging.getLogger("stockbot")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

TELEGRAM_SEND_STATS = {
    "success": 0,
    "fallback_success": 0,
    "failed": 0,
}

T = TypeVar("T")


def retry_with_backoff(func: Callable[[], T], max_retries: int = 3, base_delay: float = 1.0) -> T:
    """재시도 로직 (exponential backoff)."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                f"Attempt {attempt + 1}/{max_retries} failed (delay {delay}s): {e}"
            )
            time.sleep(delay)
    raise RuntimeError(f"Failed after {max_retries} retries")


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


def escape_telegram_markdown(text: str) -> str:
    if text is None:
        return ""
    escaped = str(text).replace("\\", "\\\\")
    for ch in ("_", "*", "[", "]", "(", ")", "`"):
        escaped = escaped.replace(ch, f"\\{ch}")
    return escaped


def get_latest_news(query: str) -> str:
    def _fetch():
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
            if title:
                news_list.append(f"- {title}")

        if not news_list:
            return "(관련 뉴스 없음)"
        return "\n".join(news_list)

    try:
        return retry_with_backoff(_fetch, max_retries=3, base_delay=0.5)
    except Exception as e:
        print(f"[News Error] {query}: {e}")
        logger.error(f"News fetch failed after retries: {query}: {e}")
        return "(뉴스 수집 실패)"


def get_news_titles_for_ai(query: str):
    def _fetch():
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

    try:
        return retry_with_backoff(_fetch, max_retries=3, base_delay=0.5)
    except Exception as e:
        print(f"[NewsTitle Error] {query}: {e}")
        logger.error(f"News title fetch failed after retries: {query}: {e}")
        return []


def send_telegram(msg: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }

    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        TELEGRAM_SEND_STATS["success"] += 1
        logger.info("Telegram message sent (markdown)")
        return True
    except Exception as e:
        print(f"[Telegram Markdown Error] {e}")
        logger.warning(f"Telegram markdown send failed: {e}")
        # Markdown 파싱 실패 시 plain text로 재시도해 신호 유실을 줄인다.
        try:
            fallback_payload = {
                "chat_id": CHAT_ID,
                "text": msg,
            }
            fallback_resp = requests.post(url, json=fallback_payload, timeout=5)
            fallback_resp.raise_for_status()
            TELEGRAM_SEND_STATS["fallback_success"] += 1
            print("[Telegram] Fallback plain text 전송 성공")
            logger.info("Telegram message sent via plain text fallback")
            return True
        except Exception as fallback_e:
            TELEGRAM_SEND_STATS["failed"] += 1
            print(f"[Telegram Error] {fallback_e}")
            logger.error(f"Telegram send failed completely: {fallback_e}")
            return False
def send_webhook_to_spring(ticker: str, signal_type: str, price: float) -> bool:
    """Spring Boot 웹 어플리케이션 아카이빙 웹훅으로 정제된 데이터를 POST 송신합니다."""
    if not SPRING_WEBHOOK_URL:
        logger.warning("Spring Webhook URL 미설정으로 송신 무시")
        return False

    payload = f"종목: {ticker}, 신호: {signal_type}, 가격: {price:.2f}"
    headers = {"Content-Type": "text/plain; charset=utf-8"}

    try:
        resp = requests.post(SPRING_WEBHOOK_URL, data=payload.encode('utf-8'), headers=headers, timeout=5)
        if resp.status_code in [200, 201]:
            logger.info(f"Spring Webhook 전송 성공: {ticker} ({signal_type})")
            return True
        else:
            logger.error(f"Spring Webhook 응답 에러 상태 코드: {resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"Spring Webhook 통신 아키텍처 장애 예외 발생: {e}")
        return False

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


# 수정 후 (bot.py)
def generate_ai_comment(prompt: str) -> str:
    try:
        if GEMINI_CLIENT is None:
            return "(AI 비활성화)"

        # 표준 GA 모델 ID 인자값으로 교정
        model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

        resp = GEMINI_CLIENT.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return resp.text
    except Exception as e:
        # 만약 또 429 에러가 나면 텔레그램 로그로 남김
        if "429" in str(e):
            return f"(할당량 초과: 잠시 후 재시도)"
        return f"(분석 실패: {e})"



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


def _get_close_series(batch_df: pd.DataFrame, ticker: str) -> Optional[pd.Series]:
    """Extract Close price Series for *ticker* from a yfinance download result.

    Handles three shapes that yfinance may return:
    - Single-ticker simple DataFrame  → ``batch_df["Close"]`` is a Series.
    - Multi-ticker batch DataFrame    → ``batch_df["Close"]`` is a DataFrame
      whose columns are the requested ticker symbols.
    - MultiIndex column batch (older yfinance) → same extraction via ``["Close"]``.

    Returns ``None`` when the ticker's data is absent or entirely NaN.
    """
    if batch_df is None or batch_df.empty:
        return None

    try:
        close = batch_df["Close"]
    except KeyError:
        return None

    if isinstance(close, pd.DataFrame):
        if ticker not in close.columns:
            return None
        series = close[ticker].dropna()
        return series if not series.empty else None

    # Series path (single-ticker download or test stub)
    series = close.dropna()
    return series if not series.empty else None


def analyze_market():
    print(f"[{datetime.now()}] Market Watch Start...")
    logger.info("Market watch started")

    market_risk = get_market_risk()
    risk_level = market_risk["level"]
    risk_score = market_risk["score"]
    risk_summary = market_risk["summary"]
    print(risk_summary)

    positions = load_positions()
    positions_updated = False

    def _scalar(x) -> float:
        return float(x.item()) if hasattr(x, "item") else float(x)

    # ---- Batch-download price history for all targets in one call ----
    all_tickers = [t["ticker"] for t in TARGETS]

    def _batch_download():
        return yf.download(
            all_tickers,
            period=HISTORY_PERIOD,
            progress=False,
            auto_adjust=False,
        )

    try:
        batch_df = retry_with_backoff(_batch_download, max_retries=3, base_delay=1.0)
    except Exception as e:
        print(f"[Batch Download Error] 가격 데이터 일괄 수신 실패: {e}")
        batch_df = pd.DataFrame()

    for item in TARGETS:
        ticker = item["ticker"]
        name = item["name"]
        market = item["market"]

        try:
            close = _get_close_series(batch_df, ticker)
            if close is None or len(close) < 60:
                print(f">> {name} ({ticker}): 데이터 부족, 건너뜀")
                continue

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

           # bot.py 수정 후 (테스트용 강제 주입)
            event_signal = "BUY"  # 무조건 BUY 신호가 터지도록 강제 설정

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

                    risk_summary_md = escape_telegram_markdown(risk_summary)
                    name_md = escape_telegram_markdown(name)
                    ticker_md = escape_telegram_markdown(ticker)
                    rating_md = escape_telegram_markdown(rating)
                    reason_text_md = escape_telegram_markdown(reason_text)
                    news_summary_md = escape_telegram_markdown(news_summary)
                    ai_comment_md = escape_telegram_markdown(ai_comment)

                    msg = (
                        f"💰 *매도(SELL) 실행*\n"
                        f"--------------------\n"
                        f"{risk_summary_md}\n"
                        f"--------------------\n"
                        f"📊 종목: {name_md} ({ticker_md})\n"
                        f"✅ 진입가: {entry_price:,.2f}\n"
                        f"💵 매도가(현재가): {curr_price:,.2f}\n"
                        f"📈 현재 RSI: {curr_rsi:.1f}\n"
                        f"📊 수익률: {roi:.2f}%\n"
                        f"레이팅: {rating_md} (Score {score}/100)\n"
                        f"사유: {reason_text_md}\n"
                        f"--------------------\n"
                        f"📰 *관련 뉴스*\n{news_summary_md}\n"
                        f"--------------------\n"
                        f"🧠 *AI 코멘트*\n{ai_comment_md}"
                    )
                    sent = send_telegram(msg)
                    if sent:
                        send_webhook_to_spring(ticker=ticker, signal_type="SELL", price=curr_price)
                        del positions[ticker]
                        positions_updated = True
                        print(f">> {name}: Position SOLD. ({reason_text})")
                    else:
                        print(f">> {name}: SELL 알림 전송 실패로 포지션 유지")
                        logger.warning(
                            "SELL signal sent failed; position kept: %s (%s)",
                            name,
                            ticker,
                        )
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

                risk_summary_md = escape_telegram_markdown(risk_summary)
                name_md = escape_telegram_markdown(name)
                ticker_md = escape_telegram_markdown(ticker)
                rating_md = escape_telegram_markdown(rating)
                news_summary_md = escape_telegram_markdown(news_summary)
                ai_comment_md = escape_telegram_markdown(ai_comment)

                msg = (
                    f"🚨 *매수(BUY) 진입*\n"
                    f"--------------------\n"
                    f"{risk_summary_md}\n"
                    f"--------------------\n"
                    f"📊 종목: {name_md} ({ticker_md})\n"
                    f"💵 진입가: {curr_price:,.2f}\n"
                    f"📈 RSI: {curr_rsi:.1f}\n"
                    f"레이팅: {rating_md} (Score {score}/100)\n"
                    f"--------------------\n"
                    f"🎯 리스크/목표 레벨(현재 진입 기준)\n"
                    f"- 손절가(-{int(STOP_LOSS_PCT*100)}%): {stop_loss:,.2f}\n"
                    f"- 1차 목표가(+{int(TARGET1_PCT*100)}%): {target1:,.2f}\n"
                    f"- 2차 목표가(+{int(TARGET2_PCT*100)}%): {target2:,.2f}\n"
                    f"- 트레일링 시작 구간(약 +{int(TRAIL_START_PCT*100)}%): {trail_start:,.2f}\n"
                    f"--------------------\n"
                    f"📰 *관련 뉴스*\n{news_summary_md}\n"
                    f"--------------------\n"
                    f"🧠 *AI 코멘트*\n{ai_comment_md}"
                )
                sent = send_telegram(msg)
                if sent:
                    send_webhook_to_spring(ticker=ticker, signal_type="BUY", price=curr_price)
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
                    print(f">> {name}: BUY 알림 전송 실패로 포지션 미생성")
                    logger.warning(
                        "BUY signal sent failed; position not created: %s (%s)",
                        name,
                        ticker,
                    )
            else:
                print(f">> {name}: No New Signal / No Position.")

        except Exception as e:
            print(f"[Error] {name} ({ticker}): {e}")
            traceback.print_exc()

    if positions_updated:
        save_positions(positions)
        print(">> positions.json updated.")

    logger.info(
        "Telegram send stats: success=%d, fallback_success=%d, failed=%d",
        TELEGRAM_SEND_STATS["success"],
        TELEGRAM_SEND_STATS["fallback_success"],
        TELEGRAM_SEND_STATS["failed"],
    )


if __name__ == "__main__":
    analyze_market()
