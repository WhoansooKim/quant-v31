# Quant V3.1 Ubuntu Edition — 레짐 적응형 퀀트 트레이딩 시스템

## 프로젝트 개요
- OS: Ubuntu 24.04 LTS (VirtualBox VM)
- DB: PostgreSQL 16 + TimescaleDB (Docker)
- 엔진: Python 3.11 (FastAPI + gRPC)
- 대시보드: Blazor Server (.NET 8)
- 캐시: Redis 7 (경량)

## 현재 상태
- Phase 1 완료: Ubuntu 환경 + Docker(PG+TimescaleDB+Redis) + Python + .NET 8
- Phase 2 완료: HMM 레짐 엔진 + Kill Switch + 5개 전략 + FinBERT
- Phase 3 진행 중: 시스템 통합 + Blazor Server + systemd

## Phase 3 범위 (현재 작업)
- Step 3.1: 8단계 오케스트레이터 (engine/api/main.py)
- Step 3.2: Blazor Server 대시보드 (dashboard/)
- Step 3.3: gRPC + Telegram + SHAP + APScheduler
- Step 3.4: systemd 서비스 + E2E 검증

## 핵심 설계 문서 (반드시 참조)
- docs/DevPlan.jsx — 전체 구축 설계서 (DB 스키마, 4-Phase 로드맵, 코드 포함)
- docs/Strategy.jsx — 전략 설계서 (HMM, Kill Switch, FinBERT, 포지션 사이징)
- docs/Phase3Guide.jsx — Phase 3 상세 구현 가이드

## 디렉토리 구조 (목표)
```
quant-v31/
├── engine/                    # Python 엔진 (FastAPI)
│   ├── api/main.py            # 오케스트레이터 + FastAPI
│   ├── api/grpc_server.py     # gRPC 서버
│   ├── data/storage.py        # PostgreSQL + Redis 저장소
│   ├── data/collector.py      # 데이터 수집기
│   ├── data/finbert_local.py  # FinBERT 로컬
│   ├── data/sentiment_hybrid.py
│   ├── strategies/base.py
│   ├── strategies/lowvol_quality.py
│   ├── strategies/vol_momentum.py
│   ├── strategies/pairs_trading.py
│   ├── strategies/vol_targeting.py
│   ├── strategies/llm_overlay.py
│   ├── risk/regime.py         # HMM 레짐 감지
│   ├── risk/regime_allocator.py
│   ├── risk/kill_switch.py
│   ├── risk/position_sizer.py
│   ├── execution/alpaca_client.py
│   ├── execution/vwap.py
│   ├── execution/scheduler.py
│   ├── execution/alerts.py
│   ├── config/settings.py
│   └── requirements.txt
├── dashboard/QuantDashboard/  # Blazor Server (.NET 8)
├── proto/                     # gRPC proto 정의
├── scripts/init_db.sql        # DB 스키마
├── systemd/                   # systemd 서비스 파일
└── docker-compose.yml
```

## DB 연결 정보
- PostgreSQL: postgresql://quant:QuantV31!Secure@localhost:5432/quantdb
- Redis: redis://localhost:6379
- conda 환경: quant-v31 (python 3.11)

## 코딩 규칙
- Python: psycopg3 사용 (psycopg[binary]), row_factory=dict_row
- SQL: TimescaleDB 함수 적극 활용 (time_bucket, 연속집계, 자동압축)
- Blazor: Npgsql Raw SQL (Entity Framework 미사용)
- 모든 시계열 테이블은 hypertable
