# bot.py-v2.0

텔레그램으로 주식 매수/매도 신호와 모닝 브리핑을 전송하는 파이썬 프로젝트입니다.

## 구성 파일

- `bot.py`: 메인 신호 분석 및 포지션 관리 스크립트
- `daily_report.py`: 일일 모닝 브리핑 전송 스크립트
- `positions.json`: 현재 보유 포지션 저장 파일
- `config/targets.json`: 감시 종목 목록
- `config/params.json`: 매매/리스크 파라미터
- `requirements.txt`: 의존 패키지 목록

## 주요 기능

- 기술 지표 기반 이벤트 신호 감지
  - RSI 과매수/과매도
  - 볼린저 밴드 상단/하단 이탈
- 시장 리스크 점수 계산(VIX, 달러지수, 미 10년물 금리)
- 신규 매수/매도 시 텔레그램 알림
- 보유 포지션 트레일링 스탑 관리
- 뉴스 요약(구글 뉴스 RSS) 포함 알림
- Gemini AI 코멘트(선택)
- 모닝 브리핑(주요 지수 + 보유 포지션 현황)

## 요구 사항

- Python 3.10+
- Telegram Bot Token / Chat ID
- (선택) Gemini API Key

## 설치

```bash
pip install -r requirements.txt
```

## 환경 변수

필수:

- `TELEGRAM_TOKEN`: 텔레그램 봇 토큰
- `CHAT_ID`: 메시지를 받을 채팅 ID

선택:

- `GEMINI_API_KEY`: Gemini 코멘트 사용 시 필요
- `GEMINI_MODEL`: 기본값 `models/gemini-flash-latest`

Windows PowerShell 예시:

```powershell
$env:TELEGRAM_TOKEN="your_telegram_bot_token"
$env:CHAT_ID="your_chat_id"
$env:GEMINI_API_KEY="your_gemini_api_key"   # 선택
$env:GEMINI_MODEL="models/gemini-flash-latest"  # 선택
```

## 설정 파일

### config/targets.json

감시할 종목 목록을 JSON 배열로 관리합니다.

예시:

```json
[
  {"ticker": "005930.KS", "name": "삼성전자", "market": "KR"},
  {"ticker": "NVDA", "name": "NVIDIA", "market": "US"}
]
```

- `ticker`: 야후 파이낸스 티커
- `name`: 표시 이름
- `market`: `KR` 또는 `US`

### config/params.json

매매/리스크 파라미터를 정의합니다.

주요 항목:

- `RSI_OVERSOLD`, `RSI_OVERBOUGHT`
- `STOP_LOSS_PCT`, `TARGET1_PCT`, `TARGET2_PCT`
- `TRAIL_START_PCT`, `TRAILING_STOP_PCT`
- `MARKET_SCORE_BLOCK_BUY`, `MARKET_SCORE_STRONG_BOOST`
- `MAX_KR_POSITIONS`

## 실행 방법

### 1) 신호 분석 실행

```bash
python bot.py
```

- 감시 종목을 순회하며 BUY/SELL 이벤트를 감지합니다.
- 매매 이벤트 발생 시 텔레그램 메시지를 전송합니다.
- 포지션 변경이 있으면 `positions.json`을 갱신합니다.

### 2) 모닝 브리핑 실행

```bash
python daily_report.py
```

- 시장 요약(S&P500, KOSPI, USD/KRW)
- 현재 보유 포지션 수익률 요약

## 운영 팁

- `positions.json`은 자동 갱신되므로 버전 관리 시 주의하세요.
- 스케줄러(작업 스케줄러, GitHub Actions, cron 등)로 정기 실행하면 편리합니다.
- 텔레그램 Markdown 파싱이 깨지지 않도록 종목명/메시지 포맷 변경 시 특수문자를 점검하세요.

## 문제 해결

- 환경변수 누락 오류:
  - `TELEGRAM_TOKEN`, `CHAT_ID`가 정확히 설정되어 있는지 확인
- 데이터 부족/수집 실패:
  - 야후 파이낸스 또는 네트워크 상태 확인
- AI 코멘트 비활성화:
  - `GEMINI_API_KEY` 설정 여부 확인
  - Gemini 할당량(429) 초과 시 잠시 후 재시도
