# Quant V4 고도화 프로젝트 — 팩터 인베스팅 / 스마트 베타 / 퀀더멘탈

> Created: 2026-03-15
> Author: Claude Code (Opus 4.6)
> Purpose: 수익률 극대화를 위한 체계적 고도화 로드맵

---

## 현재 상태 분석

### 기존 시그널 생성 (단일 팩터: 모멘텀)
```
조건: return_20d_rank ≥ 0.6 (상위 40%)
    + trend_aligned (Close > SMA50 > SMA200)
    + breakout_5d (5일 고가 돌파)
    + volume_surge (거래량 1.5x 이상)
```

### 기존 멀티팩터 스코어링 (T40+S30+F30)
| 팩터 | 가중치 | 데이터 소스 | 한계점 |
|------|--------|-----------|--------|
| Technical (T) | 40% | swing_indicators (rank, trend, breakout, volume) | 모멘텀 단일 차원 |
| Sentiment (S) | 30% | Finnhub 뉴스 → Claude/Ollama 감성분석 | 뉴스 헤드라인만 분석 |
| Flow (F) | 30% | Finnhub 내부자 + 애널리스트 | 데이터 지연 |

### 개선이 필요한 영역
1. **Technical Score**: 모멘텀만 반영, Quality/Value 팩터 없음
2. **레짐 감지**: Watchlist에만 ADX 기반 레짐 존재, 시그널 파이프라인에는 미적용
3. **펀더멘탈 분석**: SEC 파일링 분석 미활용 (EDGAR 스캔은 있으나 점수 미반영)
4. **팩터 크라우딩**: ETF 중복도 모니터링 없음
5. **공매도 잔고**: 숏스퀴즈/역발상 시그널 없음

---

## Tier 1: 멀티팩터 확장 + 레짐 적응 (즉시 적용)

> 기대 효과: +2-4% 연 알파, Sharpe 12% 향상

### Step 1.1: Quality + Value 팩터 추가

**목표**: Finnhub `get_basic_financials()` 데이터를 활용해 Quality/Value 점수 산출

**Quality Score (0-100)**:
| 지표 | 소스 | 계산 |
|------|------|------|
| ROE | Finnhub `roeTTM` | >15%: 30pt, >10%: 20pt, >5%: 10pt |
| Gross Margin | Finnhub `grossMarginTTM` | >40%: 25pt, >30%: 15pt, >20%: 10pt |
| Debt/Equity | Finnhub `totalDebt/totalEquity` | <0.5: 25pt, <1.0: 15pt, <1.5: 10pt |
| Earnings Stability | Finnhub EPS surprise history | +surprise 3연속: 20pt, 2연속: 10pt |

**Value Score (0-100)**:
| 지표 | 소스 | 계산 |
|------|------|------|
| P/E Ratio | Finnhub `peTTM` | <15: 30pt, <20: 20pt, <30: 10pt |
| P/B Ratio | Finnhub `pbAnnual` | <2: 25pt, <3: 15pt, <5: 10pt |
| FCF Yield | Finnhub `fcfPerShareTTM/price` | >5%: 25pt, >3%: 15pt, >1%: 10pt |
| EV/EBITDA | Finnhub `evToEbitda` | <10: 20pt, <15: 12pt, <20: 5pt |

**파일 변경**:
- `engine_v4/ai/multi_factor.py` — `_quality_score()`, `_value_score()` 메서드 추가
- `engine_v4/ai/data_feeds.py` — `get_basic_financials()` 이미 존재, 활용 확대

**새 스코어 구조**: T30 + S20 + F10 + Q20 + V20
| 팩터 | 기존 | 신규 |
|------|------|------|
| Technical (모멘텀) | 40% | 30% |
| Sentiment (뉴스) | 30% | 20% |
| Flow (내부자+애널) | 30% | 10% |
| Quality (퀄리티) | - | 20% |
| Value (가치) | - | 20% |

### Step 1.2: 레짐 적응형 팩터 가중치

**목표**: ADX + VIX 기반 레짐 감지를 시그널 파이프라인에 적용

**레짐별 가중치**:
```
TRENDING (ADX>25):
  Technical 35%, Quality 20%, Value 15%, Sentiment 20%, Flow 10%
  → 모멘텀/추세 강조

SIDEWAYS (ADX<20):
  Technical 15%, Quality 25%, Value 30%, Sentiment 20%, Flow 10%
  → 가치/퀄리티 강조

HIGH_VOL (VIX>25 또는 20일 변동성 상위 20%):
  Technical 10%, Quality 35%, Value 25%, Sentiment 20%, Flow 10%
  → 퀄리티/방어주 강조

MIXED (기본):
  Technical 30%, Quality 20%, Value 20%, Sentiment 20%, Flow 10%
```

**구현**:
- `engine_v4/ai/multi_factor.py` — `_detect_regime()` 메서드 추가
- ADX 계산: 기존 watchlist_backtest.py에서 가져옴
- VIX 조회: yfinance `^VIX` 심볼

### Step 1.3: 팩터 모멘텀 시그널

**목표**: 최근 1-3개월 최고 성과 팩터에 틸트

**구현**:
- 매주 토요일 유니버스 갱신 시 팩터별 수익률 계산
- 상위 2개 팩터 가중치 +5% 부스트, 하위 1개 팩터 -5%
- `swing_config`에 `factor_momentum_enabled` 키 추가

**파일 변경**:
- `engine_v4/scheduler/jobs.py` — `refresh_universe` 잡에 팩터 모멘텀 계산 추가
- `engine_v4/data/storage.py` — `swing_factor_momentum` 테이블 (또는 Redis 캐시)

### Step 1.4: DB 마이그레이션

```sql
-- swing_signals에 새 팩터 점수 컬럼 추가
ALTER TABLE swing_signals
  ADD COLUMN IF NOT EXISTS quality_score FLOAT,
  ADD COLUMN IF NOT EXISTS value_score FLOAT;

-- swing_config에 새 가중치 키 추가
INSERT INTO swing_config (key, value) VALUES
  ('factor_weight_quality', '0.2'),
  ('factor_weight_value', '0.2'),
  ('regime_adaptive_weights', 'true'),
  ('factor_momentum_enabled', 'true')
ON CONFLICT (key) DO NOTHING;
```

### Step 1.5: 대시보드 업데이트

- Signals 페이지: Quality/Value 점수 표시
- Settings 페이지: 5개 팩터 가중치 편집 + 레짐 적응 토글
- Performance 페이지: 팩터별 기여도 차트 (추후)

---

## Tier 2: 퀀더멘탈 + 데이터 확장 (중기)

> 기대 효과: 승률 15-25% 개선

### Step 2.1: LLM 펀더멘탈 분석 (SEC 10-Q/10-K)

**목표**: 시그널 승인 전 자동 재무제표 분석

**구현**:
- 기존 `engine_v4/events/edgar.py` 확장 → 10-Q/10-K 본문 다운로드
- Claude/Ollama에 핵심 섹션 전달: MD&A, Risk Factors, Financial Highlights
- 분석 결과 → `fundamental_score` (0-100)
- 새 스코어 구조: T25 + S15 + F10 + Q15 + V15 + LLM20

**분석 항목**:
| 항목 | 가중치 | 평가 기준 |
|------|--------|----------|
| 매출 성장 추이 | 30% | QoQ, YoY 성장률 |
| 마진 추이 | 25% | 영업이익률 변화 |
| 부채 건전성 | 20% | 부채비율 변화, 만기 구조 |
| 경영진 가이던스 | 25% | 구체적 숫자 vs 모호한 표현 |

### Step 2.2: 팩터 크라우딩 모니터

**목표**: 인기 팩터 ETF와의 보유 종목 중복도 추적

**ETF 추적 대상**:
- MTUM (iShares Momentum), QUAL (iShares Quality), VLUE (iShares Value)
- 중복도 >60%: 포지션 사이즈 50% 축소 또는 composite_score 기준 상향

**구현**:
- `engine_v4/ai/factor_crowding.py` 신규 모듈
- 주 1회 ETF 보유종목 갱신 (yfinance 또는 iShares API)

### Step 2.3: 공매도 잔고 데이터

**목표**: 숏스퀴즈 + 역발상 시그널

**구현**:
- Finnhub 또는 FINRA 데이터 활용
- Short Interest Ratio (SIR) > 10일: 주의 신호
- SIR 급감 + 가격 상승: 숏커버링 모멘텀 시그널 (+5pt 부스트)
- Flow Score에 통합 (기존 30% → 내부자 15% + 공매도 15%)

---

## Tier 3: 고급 ML + 대안 데이터 (장기 R&D)

> 기대 효과: Sharpe 2배 (논문 기준)

### Step 3.1: LSTM 모멘텀 예측

**목표**: 단순 20일 룩백 → 딥러닝 기반 모멘텀 방향 예측

**아키텍처**:
- 입력: 60일 가격/거래량/기술지표 시계열
- 모델: LSTM (2-layer, 64 hidden units)
- 출력: 5일 후 수익률 방향 확률
- 학습: 3년 데이터, 워크포워드 검증

**구현**:
- `engine_v4/ml/momentum_lstm.py` 신규 모듈
- PyTorch 또는 TensorFlow Lite
- 주 1회 재학습 (토요일 유니버스 갱신 시)

### Step 3.2: AQR식 가치+모멘텀 결합 포트폴리오

**목표**: 가치와 모멘텀의 음의 상관관계 활용

**구현**:
- 유니버스를 가치 순위 + 모멘텀 순위로 이중 정렬
- 두 순위 합산 상위 종목만 시그널 후보로 선정
- 기존 breakout/volume 필터는 유지

### Step 3.3: 대안 데이터 통합

**후보 데이터 소스**:
| 데이터 | 소스 | 비용 | 효과 |
|--------|------|------|------|
| 소셜 감성 | Reddit/Twitter API | 무료~저가 | 단기 예측 +15% |
| 옵션 플로우 | CBOE/Unusual Whales | 유료 | 기관 포지셔닝 감지 |
| 위성 데이터 | Planet Labs | 고가 | 소매/물류 실시간 |
| 웹 트래픽 | SimilarWeb API | 유료 | 소비자 트렌드 |

---

## 구현 순서 및 일정

| 단계 | 설명 | 예상 기간 | 의존성 |
|------|------|----------|--------|
| **1.1** | Quality + Value 팩터 추가 | 1일 | 없음 |
| **1.2** | 레짐 적응형 가중치 | 0.5일 | 1.1 |
| **1.3** | 팩터 모멘텀 시그널 | 0.5일 | 1.1 |
| **1.4** | DB 마이그레이션 | 0.5일 | 1.1 전 |
| **1.5** | 대시보드 업데이트 | 0.5일 | 1.1-1.3 |
| **2.1** | LLM 펀더멘탈 분석 | 1일 | Tier 1 |
| **2.2** | 팩터 크라우딩 모니터 | 0.5일 | Tier 1 |
| **2.3** | 공매도 잔고 데이터 | 0.5일 | Tier 1 |
| **3.1** | LSTM 모멘텀 예측 | 2-3일 | Tier 1-2 |
| **3.2** | 가치+모멘텀 결합 | 1일 | Tier 1 |
| **3.3** | 대안 데이터 통합 | 1-2일 | 데이터 계약 |

---

## 파일 변경 맵

### Tier 1
| 파일 | 변경 내용 |
|------|----------|
| `engine_v4/ai/multi_factor.py` | Quality/Value 스코어 + 레짐 감지 + 팩터 모멘텀 |
| `engine_v4/ai/data_feeds.py` | `get_basic_financials()` 결과 활용 확대 |
| `engine_v4/data/storage.py` | 새 컬럼 쿼리 + 팩터 모멘텀 저장 |
| `engine_v4/api/main.py` | 스코어링 API 응답에 새 팩터 포함 |
| `engine_v4/config/settings.py` | 새 가중치 설정 |
| `scripts/migrate_factor_enhancement.sql` | DB 마이그레이션 |
| `dashboard/.../Signals.razor` | 5팩터 점수 표시 |
| `dashboard/.../Settings.razor` | 가중치 편집 UI |

### Tier 2
| 파일 | 변경 내용 |
|------|----------|
| `engine_v4/ai/fundamental.py` | SEC 10-Q/10-K 분석 (신규) |
| `engine_v4/ai/factor_crowding.py` | ETF 중복도 모니터 (신규) |
| `engine_v4/events/edgar.py` | 10-Q/10-K 다운로드 확장 |
| `engine_v4/ai/data_feeds.py` | 공매도 잔고 조회 추가 |

### Tier 3
| 파일 | 변경 내용 |
|------|----------|
| `engine_v4/ml/momentum_lstm.py` | LSTM 모멘텀 예측 (신규) |
| `engine_v4/strategy/swing.py` | 이중 정렬 필터 추가 |
| `engine_v4/ai/social_sentiment.py` | 소셜 감성 수집 (신규) |

---

## 성과 측정 기준

| 지표 | 현재 (추정) | Tier 1 목표 | Tier 2 목표 | Tier 3 목표 |
|------|-----------|-----------|-----------|-----------|
| 연 수익률 | 8-12% | 12-16% | 16-20% | 20-25% |
| Sharpe Ratio | 0.5-0.7 | 0.7-0.9 | 0.9-1.2 | 1.2-1.8 |
| Max Drawdown | -15~-20% | -12~-15% | -10~-12% | -8~-10% |
| Win Rate | 45-50% | 50-55% | 55-60% | 60-65% |
| Profit Factor | 1.2-1.4 | 1.4-1.7 | 1.7-2.0 | 2.0-2.5 |

---

## 참고 문헌

1. MSCI Factor Indexing Through the Decades (2025)
2. Tai, Leung & Jimenez — Dynamic Factor Allocation via Regime Switching (SSRN 2025)
3. ML Enhanced Multi-Factor Quantitative Trading (arxiv:2507.07107)
4. Alpha-R1: Alpha Screening with LLM Reasoning (arxiv:2512.23515)
5. AQR — Value and Momentum Everywhere (2025 update)
6. Two Sigma — AI in Investment Management 2026 Outlook
7. CFA Institute — Momentum Investing: A Stronger Framework (2025)
