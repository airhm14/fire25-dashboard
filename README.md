# 🔥 TEAM FIRE 25 Dashboard v1.0

> **FIRE(Financial Independence, Retire Early) 달성을 위한 AI 기반 포트폴리오 전략 대시보드**

미국 ETF 4종 (QQQM · SCHD · IAU · SGOV)에 대한 실시간 모니터링, 기술적 분석, 그리고 **3개 AI(Gemini · Claude · GPT) 합의 기반 전략 오케스트레이션**을 하나의 Streamlit 대시보드로 제공합니다.

---

## 📋 목차

1. [시스템 개요](#-시스템-개요)
2. [프로젝트 구조](#-프로젝트-구조)
3. [설치 및 실행](#-설치-및-실행)
4. [대시보드 탭 구성](#-대시보드-탭-구성)
5. [투자 전략 규칙](#-투자-전략-규칙)
6. [AI 전략 시스템 (핵심)](#-ai-전략-시스템-핵심)
7. [매뉴얼 가드 (11대 투자 규칙)](#-매뉴얼-가드-11대-투자-규칙)
8. [실행 계획 & 안정화 장치](#-실행-계획--안정화-장치)
9. [백테스트 & 전략 연구실](#-백테스트--전략-연구실)
10. [데이터 소스 & 저장소](#-데이터-소스--저장소)
11. [설정 & 환경변수](#-설정--환경변수)

---

## 🏗 시스템 개요

```
┌─────────────────────────────────────────────────────┐
│                  Streamlit Dashboard                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Tab 1    │  │ Tab 2    │  │ Tab 3             │  │
│  │ 내 자산  │  │ 시장현황  │  │ 거시경제 & 전략   │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
└───────────────────────┬─────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
   ┌─────────────┐ ┌────────┐ ┌──────────────┐
   │ Data Layer  │ │ Engine │ │ AI Agents    │
   │ yfinance    │ │ Regime │ │ Gemini(뉴스) │
   │ CNN F&G     │ │ Gate   │ │ Claude(전략) │
   │ RSS News    │ │ Guard  │ │ GPT(전략)    │
   │ Google Sht  │ │ Stab.  │ │ Discussion   │
   └─────────────┘ └────────┘ └──────────────┘
```

**핵심 흐름:**
1. 시장 데이터 수집 (Yahoo Finance, CNN, RSS)
2. 기술적 지표 계산 (SMA 20/50/100/200, RSI)
3. 시장 레짐 분류 (BULL / CORRECTION / BEAR / RECOVERY)
4. AI 3자 합의 전략 도출 (Gemini → Claude vs GPT → 충돌 시 토론)
5. 매뉴얼 가드 검증 (11대 규칙)
6. Strategy Stabilizer 적용 → 최종 실행 계획

---

## 📁 프로젝트 구조

```
fire25-dashboard/
├── fire25_v1.0.py                # 메인 Streamlit 앱
├── requirements.txt              # 의존성
├── README.md                     # 시스템 매뉴얼 (이 문서)
├── GOOGLE_SHEETS_SETUP.md        # Google Sheets 연동 가이드
│
└── fire25/                       # 코어 모듈
    ├── data_provider.py          # 통합 시장 데이터 (yfinance/pykrx/pyupbit)
    ├── indicator_engine.py       # 기술적 지표 (SMA, RSI)
    ├── regime_engine.py          # 시장 레짐 분류
    ├── signals.py                # 웅덩이 신호 계산 + 쿨다운
    ├── strategy.py               # DEFCON · Smart Shoulder · Stage 배분
    ├── portfolio_engine.py       # 포트폴리오 평가/비중 계산
    ├── news_engine.py            # 뉴스 수집 & 카테고리 분류
    ├── macro_summary.py          # 거시 요약 생성
    ├── backtest.py               # 백테스트 엔진
    ├── monte_carlo.py            # FIRE 시뮬레이터
    ├── fx_provider.py            # 환율 변환 (KRW/USD)
    │
    ├── agents/                   # AI 전략 에이전트
    │   ├── gemini_agent.py       #   Gemini — 뉴스 이벤트 탐지
    │   ├── claude_agent.py       #   Claude — 독립 전략 생성 (전략가 A)
    │   └── gpt_agent.py          #   GPT — 독립 전략 생성 (전략가 B)
    │
    ├── engine/                   # AI 오케스트레이션 엔진
    │   ├── regime_gate.py        #   레짐 분류 + 3일 지속성 필터
    │   ├── orchestrator.py       #   마스터 오케스트레이터
    │   ├── conflict_detector.py  #   Claude ↔ GPT 합의/충돌 판정
    │   └── discussion_engine.py  #   1라운드 토론 엔진
    │
    ├── strategy_v2/              # 전략 실행 레이어
    │   ├── manual_guard.py       #   매뉴얼 가드 (11대 규칙)
    │   ├── portfolio_strategy.py #   포트폴리오 컨텍스트 빌더
    │   └── execution_plan.py     #   실행 계획 + Strategy Stabilizer
    │
    ├── ai/                       # AI 하위 모듈
    │   ├── gemini_events.py      #   Gemini 이벤트 탐지 (핵심)
    │   ├── model_registry.py     #   모델명 레지스트리
    │   ├── ai_router.py          #   멀티 AI 라우터
    │   └── ...
    │
    └── storage/                  # 영속 저장
        ├── portfolio_storage.py  #   Google Sheets CRUD
        └── portfolio_history.py  #   이력 차트 렌더링
```

---

## 🚀 설치 및 실행

### 요구 사항
- Python 3.11+
- API 키: Gemini, Claude (Anthropic), OpenAI
- (선택) Google Sheets 서비스 계정

### 설치

```bash
cd fire25-dashboard
pip install -r requirements.txt
```

### Secrets 설정

`.streamlit/secrets.toml` 파일 생성:

```toml
password = "대시보드_접속_비밀번호"

GEMINI_API_KEY   = "your-gemini-api-key"
ANTHROPIC_API_KEY = "your-anthropic-api-key"
OPENAI_API_KEY   = "your-openai-api-key"

[models]
gemini = "gemini-2.5-flash"
claude = "claude-sonnet-4-6"
openai = "gpt-4o-mini"

# (선택) Google Sheets
spreadsheet_url = "https://docs.google.com/spreadsheets/d/..."
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@...iam.gserviceaccount.com"
# ... 나머지 필드
```

### 실행

```bash
streamlit run fire25_v1.0.py
```

---

## 📊 대시보드 탭 구성

### Tab 1 — 내 자산 현황

| 섹션 | 설명 |
|------|------|
| 포트폴리오 요약 | 총 자산, 일간 손익, 목표 대비 편차 |
| 자산 비중 차트 | 도넛 차트 (QQQM/SCHD/IAU/현금) |
| 포트폴리오 이력 | Google Sheets 기반 자산 추이 그래프 |
| FIRE 시뮬레이터 | Monte Carlo 시뮬레이션 (성공 확률, 경로 시각화) |

### Tab 2 — 시장 현황

| 섹션 | 설명 |
|------|------|
| 실시간 시세 | QQQM · SCHD · IAU · SGOV 가격/등락률/거래량 |
| VIX & 공포·탐욕 지수 | 변동성 상태 + 센티먼트 카드 |
| 시장 레짐 / 핵심 지표 | BULL/CORRECTION/BEAR/RECOVERY + VIX/F&G/10Y/유가 |
| 오늘의 시장 동인 | 자산별 뉴스 요약 + 방향 해석 |
| QQQM 기술적 지표 | RSI · SMA20/50/100/200 카드 |
| QQQM 기술적 분석 | 캔들스틱 차트 + SMA 오버레이, RSI 차트 |
| 백테스트 (실험) | 웅덩이 전략 과거 성과 시뮬레이션 |
| 전략 연구실 | 파라미터 민감도 분석 (현금비중, 쿨다운, 다중자산) |

### Tab 3 — 거시경제 & 전략

| 섹션 | 설명 |
|------|------|
| 시장 이벤트 | VIX 급등, 유가 급변, 지정학 리스크 등 감지 |
| 리스크 레이더 | 금리/인플레이션/지정학/시장스트레스 (0-100 게이지) |
| **AI 전략 오케스트레이터** | 🚀 버튼 → 3~5 API 콜 → 최종 전략 도출 |
| 포트폴리오 관점 | 자산별 시장 시사점 |
| 체크 포인트 | 주요 모니터링 항목 |
| 대표 뉴스 | 최근 핵심 기사 |

---

## 📐 투자 전략 규칙

### 목표 배분 비중 (72/16/2/10)

| 자산 | 목표 비중 | 역할 |
|------|----------|------|
| **QQQM** | 72% | 성장 코어 (Nasdaq-100) |
| **SCHD** | 16% | 배당 성장 |
| **IAU** | 2% | 금 헤지 |
| **SGOV/현금** | 10% | 현금성 완충 |

### DEFCON 세이빙

> VIX ≤ 14 **AND** RSI ≥ 70 → 시장 과열

- 신규 자금 100%를 SGOV로 배분
- QQQM/SCHD/IAU 매수 차단
- 시장 과열기에 현금을 지켜 다음 조정 시 매수 여력 확보

### 웅덩이 전략 (Puddle Strategy)

가격이 이동평균선을 하향 돌파할 때 단계적으로 매수하는 전략:

| 단계 | 조건 | 투입 비율 |
|------|------|----------|
| Stage 0 | 정상 (SMA50 상회) | 0% (대기) |
| Stage 1 | SMA50 하향 이탈 | 현금의 10% |
| Stage 2 | SMA100 하향 이탈 | 현금의 25% |
| Stage 3 | SMA200 하향 이탈 | 현금의 50% |

- **30일 쿨다운**: 동일 단계 중복 매수 방지
- **투입 대상**: 목표 비중(72/16/2/10)에 맞춰 즉시 배분

### Smart Shoulder 리밸런싱

> QQQM 비중 > 77% **AND** 가격 < SMA20 **AND** 최근 고점 근접

- QQQM 일부 매도 → 72/16/2/10 복귀
- QQQM은 코어 자산이므로 이 조건 외에는 HOLD가 기본

### QQQM 비중 캡 존

| 비중 구간 | 규칙 |
|-----------|------|
| ≤ 70% | 자유 매수 |
| 70 ~ 77% | 소량 매수 허용 |
| 77 ~ 80% | 신규 매수 불가, 하향 조정 고려 |
| > 80% | **반드시** 감량 |

---

## 🤖 AI 전략 시스템 (핵심)

### 전체 흐름도

```
🚀 AI 전략 실행 버튼 클릭
        │
        ▼
┌─────────────────────────────┐
│  1. Regime Gate             │  레짐 분류 + 3일 지속성 필터
│     NORMAL / DEFCON /       │  ※ 레짐 미변경 시 이전 전략 재사용 (0콜)
│     PUDDLE_1~4 /            │
│     SMART_SHOULDER          │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│  2. Gemini 이벤트 브리프    │  API 콜 #1
│     뉴스 → 헤드라인 요약    │  gemini-2.5-flash
│     거시 드라이버 추출      │
│     리스크 레벨 판정        │
└─────────────┬───────────────┘
              ▼
     ┌────────┴────────┐
     ▼                 ▼
┌──────────┐    ┌──────────┐
│ 3. Claude│    │ 4. GPT   │  API 콜 #2, #3
│ (전략가A)│    │ (전략가B)│  독립적으로 전략 생성
│ claude-  │    │ gpt-4o-  │
│ sonnet-  │    │ mini     │
│ 4-6      │    │          │
└────┬─────┘    └────┬─────┘
     │               │
     └───────┬───────┘
             ▼
┌─────────────────────────────┐
│  5. 충돌 감지               │  합의 or 충돌 판정
│     방향 불일치? 비중±10%?  │
│     현금±20%? 신뢰도±25?    │
└─────────────┬───────────────┘
         ┌────┴────┐
    합의  │        │ 충돌
         ▼        ▼
   높은 신뢰도  ┌─────────────────┐
   전략 채택    │ 6. 토론 (1라운드)│  API 콜 #4, #5
               │ Claude→GPT 반박  │
               │ GPT→최종 결정    │
               └────────┬────────┘
                        ▼
┌─────────────────────────────┐
│  7. Manual Guard            │  11대 규칙 검증
│     위반 시 전 종목 HOLD    │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│  8. Strategy Stabilizer     │  일일 변동 제한
│     ±5% 비중 변동 캡        │
│     최소 1% 거래 필터       │
│     일일 현금 25% 캡        │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│  9. 실행 계획 출력          │
│     종목별 BUY/HOLD/REDUCE  │
│     주수, 예상 비용         │
│     PUDDLE 투입률 적용      │
└─────────────────────────────┘
```

### API 사용량

| 시나리오 | API 콜 수 | 설명 |
|---------|----------|------|
| 레짐 미변경 | 0 | 이전 전략 재사용 |
| 합의 | 3 | Gemini + Claude + GPT |
| 충돌 → 토론 | 5 | + Claude 검토 + GPT 반영 |

### 각 AI 에이전트 상세

#### 💎 Gemini (뉴스 이벤트 탐지)

- **모델**: `gemini-2.5-flash`
- **역할**: 뉴스 및 시장 이벤트 요약
- **입력**: RSS 수집 뉴스 기사, 집계된 시그널, 테마 정보
- **출력**:
  ```
  headline_summary  — 종합 이벤트 요약 (한국어)
  macro_drivers     — 핵심 거시 드라이버 목록
  market_implication — 시장 시사점
  risk_level        — LOW / MODERATE / HIGH
  ```

#### 🔮 Claude (전략가 A)

- **모델**: `claude-sonnet-4-6`
- **역할**: 독립적 포트폴리오 전략 생성
- **프롬프트에 포함되는 투자 철학**:
  - Buy Fear · Rebalance Strength · Protect Core Asset · Compound Long Term
  - 72/16/2/10 목표 비중
  - QQQM 코어 자산 규칙, 비중 캡 존
  - 레짐별 AI 권한 (NORMAL/DEFCON/PUDDLE/SMART_SHOULDER)
  - 전략 안정성 규칙 (일일 ±5%, 최소 1%, SGOV ≤20%, 현금 ≤25%)
- **출력 JSON**:
  ```json
  {
    "market_view": "시장 해석 1-2문장",
    "strategy_reason": "전략 근거 1-2문장",
    "recommended_actions": [
      {"ticker": "QQQM", "action": "BUY|HOLD|REDUCE", "amount": 5},
      {"ticker": "SCHD", "action": "HOLD", "amount": 0},
      {"ticker": "IAU",  "action": "HOLD", "amount": 0},
      {"ticker": "SGOV", "action": "HOLD", "amount": 0}
    ],
    "cash_action": "KEEP|DEPLOY|INCREASE",
    "confidence_score": 72
  }
  ```

#### 🧠 GPT (전략가 B)

- **모델**: `gpt-4o-mini`
- **역할**: Claude와 동일한 입력으로 독립 전략 생성
- **프롬프트**: Claude와 동일한 투자 규칙/철학 포함
- **목적**: 두 AI의 독립적 관점으로 편향 제거 + 교차 검증

### 충돌 감지 기준

두 전략가의 결과를 비교하여 합의/충돌을 판정합니다:

| 기준 | 합의 | 충돌 |
|------|------|------|
| 매매 방향 | 동일 (BUY↔BUY) | 반대 (BUY↔REDUCE) |
| 비중 차이 | < 10% | ≥ 10% |
| 현금 전략 | 동일 (KEEP↔KEEP) | 불일치 |
| 현금 사용량 | 차이 < 20% | 차이 ≥ 20% |
| 신뢰도 | 차이 < 25 | 차이 ≥ 25 |

하나라도 충돌 → 토론 발동

### 토론 메커니즘 (1라운드)

충돌 시 최대 1라운드의 구조화된 토론이 진행됩니다:

1. **Claude 검토**: GPT 전략 + 충돌 사유를 보고 반박/수정안 제시
2. **GPT 반영**: Claude의 피드백을 참고해 최종 전략 결정

> 무한 루프 방지를 위해 정확히 1라운드만 진행합니다.

### 전략 일관성 (Strategy Consistency)

- 레짐이 이전 실행과 동일하면 새 API 호출 없이 **이전 전략을 유지**
- 불필요한 API 비용 절감 + 잦은 전략 변경 방지

---

## 🛡 매뉴얼 가드 (11대 투자 규칙)

AI가 도출한 전략이 투자 매뉴얼을 위반하지 않는지 최종 검증합니다.
위반 발견 시 **전 종목 HOLD로 보정**합니다.

| # | 규칙 | 설명 |
|---|------|------|
| 1 | 허용 종목 | QQQM, SCHD, IAU, SGOV만 거래 가능 |
| 2 | 허용 액션 | BUY, HOLD, REDUCE만 가능 |
| 3 | 현금 액션 | KEEP, DEPLOY, INCREASE만 가능 |
| 4 | 정수 주문 | 소수점 주문 불가 (정수 주만 허용) |
| 5 | 레짐 규칙 | DEFCON: 성장자산 매수 차단 / SMART_SHOULDER: QQQM 매수 차단 |
| 6 | QQQM 코어 | 기본 HOLD, REDUCE는 Smart Shoulder 또는 구조적 리스크만 |
| 7 | QQQM 캡 존 | >80%이면 반드시 감량, 77-80%이면 매수 불가 |
| 8 | 편차 한도 | QQQM ±5%, SCHD ±3%, IAU ±2% |
| 9 | SGOV 상한 | 최대 20% (DEFCON 제외) |
| 10 | 일일 비중 변동 | 최대 ±5%/일 |
| 11 | 일일 현금 사용 | 최대 25%/일 |

---

## ⚖️ 실행 계획 & 안정화 장치

AI 전략을 실제 주문으로 변환할 때 적용되는 안전장치:

### Strategy Stabilizer

| 파라미터 | 값 | 설명 |
|---------|-----|------|
| 일일 비중 변동 캡 | ±5% | 하루 최대 비중 변화 |
| 최소 거래 필터 | 1% | 포트폴리오 대비 1% 미만 거래 → HOLD로 전환 |
| 일일 현금 사용 캡 | 25% | 가용 현금의 25% 이상 사용 불가 |
| SGOV 비중 상한 | 20% | 과도한 현금 편중 방지 |

### PUDDLE 투입률

웅덩이 단계에서 실제 투입 가능 금액을 제한합니다:

| 단계 | 투입률 | 설명 |
|------|--------|------|
| PUDDLE 1 | 0% | SMA50 이탈 — 관망 대기 |
| PUDDLE 2 | 10% | SMA100 이탈 — 소량 진입 |
| PUDDLE 3 | 25% | SMA200 이탈 — 본격 매수 |
| PUDDLE 4 | 50% | 회복 중 — 적극 배분 |

---

## 🧪 백테스트 & 전략 연구실

### 백테스트 (실험 모드)

웅덩이 전략의 과거 성과를 시뮬레이션합니다:

- **데이터**: QQQM 과거 OHLCV + SMA 50/100/200
- **규칙**: D일 종가 신호 → D+1 시가 체결
- **지표**: CAGR, 총수익률, 벤치마크 수익률, MDD, 샤프 지수, 거래 횟수
- **변동성 조정**: 현재 변동성 대비 투입 규모 조절 옵션

### 전략 연구실

파라미터를 바꿔가며 전략을 실험하는 샌드박스:

| 연구 모드 | 설명 |
|-----------|------|
| 단일 실행 | 단계별 투입 비율 직접 설정 후 실행 |
| 현금 비중 연구 | 현금 비중(5~30%)에 따른 CAGR/Sharpe/MDD 비교 |
| 쿨다운 연구 | 쿨다운 일수(10~60일)에 따른 성과 비교 |
| 다중 자산 검증 | QQQM vs SPY vs VTI vs BTC-USD 성과 비교 |

---

## 📡 데이터 소스 & 저장소

### 마켓 데이터

| 소스 | 데이터 | 지연 |
|------|--------|------|
| Yahoo Finance (yfinance) | QQQM/SCHD/IAU/SGOV/VIX/^TNX/CL=F | 15-20분 |
| CNN Fear & Greed | 공포·탐욕 지수 (0-100) | 실시간 |
| RSS (Google/Reuters/CNBC 등) | 뉴스 헤드라인 | 실시간 |

### 영속 저장 (Google Sheets)

- **포트폴리오 워크시트**: Date, QQQM, SCHD, IAU, SGOV, Cash, NewCash, TotalValue
- **기능**: 스냅샷 저장/로드, 이력 조회, 추이 차트
- **설정 가이드**: [GOOGLE_SHEETS_SETUP.md](GOOGLE_SHEETS_SETUP.md) 참조

---

## ⚙️ 설정 & 환경변수

### 필수 API 키

| 키 | 용도 | 발급처 |
|----|------|--------|
| `GEMINI_API_KEY` | 뉴스 이벤트 분석 | [Google AI Studio](https://aistudio.google.com) |
| `ANTHROPIC_API_KEY` | 전략 생성 (전략가 A) | [Anthropic Console](https://console.anthropic.com) |
| `OPENAI_API_KEY` | 전략 생성 (전략가 B) | [OpenAI Platform](https://platform.openai.com) |

### 모델 설정 (선택)

`[models]` 섹션에서 모델명을 오버라이드할 수 있습니다:

```toml
[models]
gemini = "gemini-2.5-flash"      # 기본값
claude = "claude-sonnet-4-6"     # 기본값
openai = "gpt-4o-mini"           # 기본값
```

### 주요 의존성

```
streamlit>=1.32     pandas          yfinance
plotly              requests        feedparser
openai>=1.40.0      anthropic>=0.34.0   google-genai>=1.0.0
gspread             google-auth     pytz
```

---

## 📌 주의사항

- 본 대시보드는 **투자 참고용**이며, 투자 결정은 본인 책임입니다.
- AI 전략은 시장 상황에 따라 달라지며 과거 성과가 미래를 보장하지 않습니다.
- Yahoo Finance 데이터는 15-20분 지연됩니다.
- API 비용은 사용자 부담입니다 (기본 3콜/실행, 최대 5콜).

---

<p align="center">
  <b>TEAM FIRE 25</b> · 투자 매뉴얼 v5.10 기반 · 2025
</p>
