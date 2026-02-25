import { useState } from "react";

// ─── Design System ───
const C = {
  bg: "#05060b", s1: "#0a0c15", s2: "#0f111c", s3: "#141729",
  bd: "#1c2040", t: "#a8afc4", tm: "#555d78", tb: "#dde1ed", tw: "#f0f2f8",
  emerald: "#10b981", blue: "#3b82f6", violet: "#8b5cf6",
  amber: "#f59e0b", rose: "#f43f5e", cyan: "#06b6d4",
  orange: "#f97316", lime: "#84cc16", pink: "#ec4899",
};

const Card = ({ children, s, accent }) => (
  <div style={{ background: C.s1, borderRadius: 10, border: `1px solid ${C.bd}`, padding: "14px 16px",
    ...(accent ? { borderLeft: `3px solid ${accent}` } : {}), ...s }}>{children}</div>
);
const Sec = ({ children, c = C.blue }) => (
  <div style={{ fontWeight: 800, color: C.tb, fontSize: 14, margin: "22px 0 10px", paddingBottom: 7,
    borderBottom: `2px solid ${c}28`, display: "flex", alignItems: "center", gap: 8 }}>
    <div style={{ width: 3, height: 16, background: c, borderRadius: 2 }} />{children}
  </div>
);
const Info = ({ c, icon, title, children }) => (
  <div style={{ background: `${c}06`, border: `1px solid ${c}18`, borderRadius: 10, padding: "12px 14px", margin: "10px 0" }}>
    <div style={{ color: c, fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{icon} {title}</div>
    <div style={{ color: C.t, fontSize: 11.5, lineHeight: 1.75 }}>{children}</div>
  </div>
);
const Tag = ({ children, c = C.blue }) => (
  <span style={{ background: `${c}14`, color: c, padding: "1px 7px", borderRadius: 4,
    fontSize: 9.5, fontFamily: "monospace", fontWeight: 700 }}>{children}</span>
);
const Pre = ({ children }) => (
  <pre style={{ color: C.emerald, fontSize: 9.5, lineHeight: 1.5,
    fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace",
    margin: "6px 0", overflowX: "auto", whiteSpace: "pre", padding: "12px 14px",
    background: "#04050a", borderRadius: 8, border: `1px solid ${C.bd}` }}>{children}</pre>
);
const Stat = ({ items }) => (
  <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(items.length, 4)}, 1fr)`, gap: 6, margin: "8px 0" }}>
    {items.map((it, i) => (
      <div key={i} style={{ background: C.s2, borderRadius: 8, padding: "10px 12px", border: `1px solid ${C.bd}`,
        boxShadow: `0 0 12px ${it.c}08` }}>
        <div style={{ color: it.c, fontSize: 9.5, fontWeight: 600, marginBottom: 2 }}>{it.label}</div>
        <div style={{ color: C.tw, fontSize: 16, fontWeight: 800 }}>{it.value}</div>
        {it.sub && <div style={{ color: C.tm, fontSize: 9, marginTop: 1 }}>{it.sub}</div>}
      </div>
    ))}
  </div>
);
const Chk = ({ items, c = C.emerald }) => items.map((x, i) => (
  <div key={i} style={{ display: "flex", gap: 8, padding: "4px 0", fontSize: 11, color: C.t }}>
    <span style={{ color: c, flexShrink: 0 }}>☐</span><span>{x}</span>
  </div>
));
const Tbl = ({ headers, rows, colors }) => (
  <div style={{ borderRadius: 8, overflow: "hidden", border: `1px solid ${C.bd}`, margin: "8px 0", fontSize: 11 }}>
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${headers.length}, 1fr)`, background: C.s3, padding: "6px 10px" }}>
      {headers.map((h, i) => <span key={i} style={{ color: colors?.[i] || C.tm, fontWeight: 700, fontSize: 10 }}>{h}</span>)}
    </div>
    {rows.map((r, i) => (
      <div key={i} style={{ display: "grid", gridTemplateColumns: `repeat(${headers.length}, 1fr)`,
        padding: "5px 10px", background: i % 2 === 0 ? C.s1 : "transparent", borderTop: `1px solid ${C.bd}06` }}>
        {r.map((cell, j) => <span key={j} style={{ color: j === 0 ? C.tb : C.t, fontWeight: j === 0 ? 600 : 400 }}>{cell}</span>)}
      </div>
    ))}
  </div>
);

// ═══════════════════════════════════════════════════════════════
// TAB 1: OVERVIEW
// ═══════════════════════════════════════════════════════════════
function Overview() {
  return (<div>
    <Info c={C.emerald} icon="🐧" title="V3.1 Ubuntu Edition — 인프라 전면 변경">
      OS: <b>Ubuntu 24.04 LTS</b> / DB: <b>PostgreSQL 16 + TimescaleDB</b> / Dashboard: <b>Blazor Server (.NET 8)</b><br />
      TimescaleDB가 Redis TimeSeries 역할을 대체 → Redis는 단순 캐시 전용으로 경량화. 모든 시계열(가격, 레짐, 센티먼트)을 PostgreSQL 단일 DB로 통합.
    </Info>

    <Sec c={C.cyan}>인프라 변경 요약</Sec>
    <Tbl headers={["항목", "V3.1 기존", "V3.1 Ubuntu Ed.", "변경 이유"]}
      rows={[
        ["OS", "Windows Server", "Ubuntu 24.04 LTS", "Docker 네이티브, 리소스 20~30% 절감"],
        ["DB", "MSSQL 2022", "PostgreSQL 16", "무료, Python 궁합 최고, JSONB 지원"],
        ["시계열", "Redis TimeSeries", "TimescaleDB 확장", "PG 안에서 통합, 자동 압축"],
        ["캐시", "Redis Stack", "Redis 7 (캐시 전용)", "TimescaleDB가 TS 대체, Redis 경량화"],
        ["대시보드", "MAUI Blazor Hybrid", "Blazor Server WebApp", "Linux 완벽 지원, 브라우저 접속"],
        ["ORM", "pyodbc + SQLAlchemy", "psycopg3 + SQLAlchemy", "더 빠르고 안정적"],
        ["C# 연결", "MSSQL Npgsql", "Npgsql (PostgreSQL)", "성숙한 .NET PG 드라이버"],
        ["스케줄러", "APScheduler", "APScheduler + systemd", "OS 레벨 자동 재시작"],
      ]} />

    <Sec c={C.violet}>프로젝트 디렉토리 구조</Sec>
    <Pre>{`quant-v31/
├── engine/                        # Python 전략 엔진 (FastAPI)
│   ├── api/
│   │   ├── main.py                # FastAPI 진입점 + 오케스트레이터
│   │   ├── routes/
│   │   │   ├── signals.py         # 시그널 API
│   │   │   ├── portfolio.py       # 포트폴리오 API
│   │   │   ├── backtest.py        # 백테스트 API
│   │   │   ├── regime.py          # 레짐 상태 API
│   │   │   └── health.py
│   │   └── grpc_server.py         # Blazor Server gRPC 연동
│   ├── data/
│   │   ├── collector.py           # yfinance + Alpaca 수집기
│   │   ├── fundamental.py         # SEC EDGAR 재무 데이터
│   │   ├── macro.py               # FRED 매크로 지표
│   │   ├── insider.py             # EDGAR Form 4
│   │   ├── finbert_local.py       # FinBERT 로컬 엔진
│   │   ├── sentiment_hybrid.py    # FinBERT+Claude 하이브리드
│   │   ├── reddit_collector.py    # Reddit/WSB 수집기
│   │   ├── options_iv.py          # 옵션 내재변동성
│   │   └── storage.py             # ★ PostgreSQL + TimescaleDB + Redis
│   ├── strategies/
│   │   ├── base.py                # 전략 추상 (레짐 인터페이스)
│   │   ├── lowvol_quality.py      # ① Low-Vol + Quality
│   │   ├── vol_momentum.py        # ② Vol-Managed 모멘텀
│   │   ├── pairs_trading.py       # ③ 페어즈/Mean-Reversion
│   │   ├── vol_targeting.py       # ④ Volatility Targeting
│   │   └── llm_overlay.py         # ⑤ FinBERT+Claude 센티먼트
│   ├── risk/
│   │   ├── manager.py             # 통합 리스크 (레짐 연동)
│   │   ├── regime.py              # HMM 3-State 레짐 감지
│   │   ├── regime_allocator.py    # 레짐별 배분 매트릭스
│   │   ├── kill_switch.py         # 3단계 Kill Switch
│   │   ├── position_sizer.py      # ATR+Vol역가중 동적 사이징
│   │   └── stop_loss.py
│   ├── execution/
│   │   ├── alpaca_client.py       # Alpaca API 래퍼
│   │   ├── vwap.py                # VWAP 분할 실행
│   │   ├── scheduler.py           # APScheduler
│   │   └── alerts.py              # Telegram Bot
│   ├── backtest/
│   │   ├── vectorbt_engine.py     # VectorBT 백테스트
│   │   ├── walk_forward.py        # Walk-Forward 검증
│   │   ├── dsr.py                 # Deflated Sharpe Ratio
│   │   ├── monte_carlo.py         # Monte Carlo 시뮬레이션
│   │   ├── regime_stress.py       # 레짐 전환 스트레스
│   │   └── granger_test.py        # 센티먼트 선행성
│   ├── explain/
│   │   ├── feature_importance.py  # SHAP 기반 설명
│   │   └── regime_visualizer.py   # 레짐 시각화
│   ├── config/
│   │   ├── settings.py            # Pydantic 설정
│   │   └── strategies.yaml
│   ├── requirements.txt
│   └── Dockerfile
├── dashboard/                     # ★ Blazor Server WebApp (.NET 8)
│   ├── QuantDashboard/
│   │   ├── Program.cs             # ★ WebApplication Builder
│   │   ├── Components/
│   │   │   ├── App.razor
│   │   │   ├── Layout/
│   │   │   │   ├── MainLayout.razor
│   │   │   │   └── NavMenu.razor
│   │   │   └── Pages/
│   │   │       ├── Home.razor         # 메인 P&L + 레짐 게이지
│   │   │       ├── Strategies.razor   # 전략별 현황
│   │   │       ├── Risk.razor         # Kill Switch 모니터
│   │   │       ├── Regime.razor       # 레짐 대시보드
│   │   │       ├── Sentiment.razor    # 센티먼트 히트맵
│   │   │       └── Backtest.razor     # 백테스트 결과
│   │   ├── Services/
│   │   │   ├── GrpcClient.cs          # Python gRPC 연동
│   │   │   ├── PostgresService.cs     # ★ Npgsql 직접 조회
│   │   │   └── RealtimeHub.cs         # ★ SignalR Hub
│   │   ├── appsettings.json
│   │   └── QuantDashboard.csproj
│   └── Dockerfile
├── proto/
│   ├── signals.proto
│   ├── portfolio.proto
│   ├── regime.proto
│   └── backtest.proto
├── scripts/
│   ├── init_db.sql                # ★ PostgreSQL + TimescaleDB
│   ├── seed_data.py
│   └── deploy.sh
├── systemd/                       # ★ Ubuntu 서비스 관리
│   ├── quant-engine.service
│   ├── quant-dashboard.service
│   └── quant-scheduler.service
├── docker-compose.yml
└── README.md`}</Pre>

    <Sec c={C.amber}>데이터 흐름도 (Ubuntu Edition)</Sec>
    <Pre>{`[데이터 수집 레이어] ──────── Ubuntu 24.04 LTS ────────
  yfinance(일봉) ──────┐
  Alpaca(실시간) ──────┤
  FRED(매크로) ────────┤──▶ ★ PostgreSQL 16 + TimescaleDB
  EDGAR(재무/Form4) ───┤       │ hypertable: 가격, 레짐, 센티먼트
  Reddit/WSB ──────────┤       │ 자동 압축: 15년 데이터 70% 절감
  News Headlines ──────┘       │ 연속 집계: 1분/1시간/1일 자동 생성
                               │
                          ┌────┴──────────────────────────────┐
                          │  🧠 FinBERT 로컬 (1차: 무료 대량)  │
                          │  → Claude API (2차: 강신호만)      │
                          └────┬──────────────────────────────┘
                               │ 센티먼트 스코어
  ┌────────────────────────────┼─────────────────────────────┐
  │         🎯 HMM 레짐 감지 엔진 (3-State)                   │
  │  Features: SPY수익률 + 21일Vol + VIX + 장단기스프레드      │
  │  Output: Bull / Sideways / Bear (확률)                    │
  └────────────┬──────────────────────────────────────────────┘
               │
  ┌────────────┴──────────────────────────────────────────────┐
  │              📊 레짐 적응형 전략 엔진 (FastAPI)             │
  │  레짐 배분 → 5 전략 시그널 → 센티먼트 오버레이             │
  │  → Vol-Targeting → Kill Switch → ATR 사이징 → VWAP       │
  └────────────┬──────────────────────────────────────────────┘
     ┌─────────┼──────────────────┐
     ▼         ▼                  ▼
  [Alpaca]  [PostgreSQL]    [★ Blazor Server :5000]
  주문실행  거래/성과/레짐    브라우저 접속 (PC/모바일)
                              레짐 게이지 + Kill Switch
                              센티먼트 히트맵 + SHAP
                              SignalR 실시간 푸시
                              Telegram 알림`}</Pre>

    <Sec c={C.rose}>기술 스택 상세</Sec>
    {[
      { cat: "🐧 인프라 (Ubuntu)", items: [
        ["Ubuntu 24.04 LTS", "장기지원 (2029년까지), 서버 최적"],
        ["Docker Engine 26+", "네이티브 Linux (Desktop 불필요, 더 빠름)"],
        ["Docker Compose 2.24+", "멀티 서비스 오케스트레이션"],
        ["systemd", "서비스 자동 시작/재시작/로그"],
        ["nginx (옵션)", "리버스 프록시, HTTPS 터미널"],
      ]},
      { cat: "🐘 데이터베이스", items: [
        ["PostgreSQL 16", "메인 DB, JSONB, 파티셔닝, CTE"],
        ["TimescaleDB 2.14+", "★ 시계열 hypertable, 자동 압축, 연속집계"],
        ["Redis 7 (옵션)", "실시간 캐시 전용 (TimescaleDB가 TS 대체)"],
        ["Parquet (PyArrow 15+)", "15년 원시 데이터 컬럼스토어 백업"],
      ]},
      { cat: "🐍 Python 엔진", items: [
        ["FastAPI 0.115+", "비동기 REST + WebSocket + gRPC"],
        ["psycopg3 3.1+", "★ PostgreSQL 비동기 드라이버 (최신)"],
        ["SQLAlchemy 2.0+", "ORM (PostgreSQL dialect)"],
        ["Polars 1.0+", "고속 데이터 처리"],
        ["hmmlearn 0.3+", "HMM 레짐 감지"],
        ["transformers 4.40+", "FinBERT 로컬"],
        ["torch 2.2+ (CPU)", "PyTorch CPU 추론"],
        ["VectorBT 0.26+", "벡터화 백테스트"],
        ["SHAP 0.45+", "Feature Importance"],
        ["alpaca-py 0.30+", "Trading API"],
        ["grpcio 1.60+", "Blazor gRPC 연동"],
      ]},
      { cat: "🔷 C# 대시보드", items: [
        [".NET 8 Blazor Server", "★ Linux 완벽 지원, 브라우저 접속"],
        ["Npgsql 8.0+", "★ PostgreSQL .NET 드라이버"],
        ["Grpc.Net.Client 2.60+", "Python gRPC 연동"],
        ["DevExpress Blazor 24.1+", "차트/그리드 (Server 호환)"],
        ["SignalR", "★ 실시간 양방향 (레짐 변경 즉시 푸시)"],
      ]},
    ].map((g, gi) => (
      <div key={gi} style={{ marginBottom: 14 }}>
        <div style={{ color: C.amber, fontWeight: 700, fontSize: 12, marginBottom: 6 }}>{g.cat}</div>
        {g.items.map((it, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "170px 1fr", gap: 8, padding: "3px 10px",
            background: i % 2 === 0 ? C.s1 : "transparent", borderRadius: 4, fontSize: 10.5, alignItems: "center" }}>
            <span style={{ color: it[0].includes("★") ? C.rose : C.blue, fontWeight: 600 }}>{it[0]}</span>
            <span style={{ color: C.tm }}>{it[1]}</span>
          </div>
        ))}
      </div>
    ))}

    <Sec c={C.lime}>월간 운영 비용</Sec>
    <Tbl headers={["항목", "비용", "비고"]}
      rows={[
        ["Ubuntu", "$0", "무료 오픈소스"],
        ["PostgreSQL+TimescaleDB", "$0", "무료 (Apache 2.0 라이센스)"],
        ["Alpaca", "$0", "커미션 프리"],
        ["Claude API", "$2~5", "FinBERT 1차 필터로 90% 절감"],
        ["Polygon.io", "$0~29", "옵션 IV (옵션)"],
        ["합계", "$2~34/월", "MSSQL 라이센스 불필요"],
      ]} />
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// TAB 2: PHASE 1
// ═══════════════════════════════════════════════════════════════
function Phase1() {
  return (<div>
    <Info c={C.blue} icon="🔧" title="Phase 1: Ubuntu 환경 + PostgreSQL/TimescaleDB + 데이터 인프라 (1~4개월)">
      Ubuntu 서버 세팅 → Docker(PostgreSQL+TimescaleDB+Redis) → Python 환경 → 데이터 수집 → HMM 프로토타입 → FinBERT 벤치마크 → Alpaca 연동
    </Info>

    <Sec c={C.blue}>Step 1.1 — Ubuntu 서버 초기 세팅</Sec>
    <Pre>{`# ── Ubuntu 24.04 LTS 초기 설정 ──

# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 필수 패키지
sudo apt install -y curl git htop tmux build-essential \\
  software-properties-common apt-transport-https ca-certificates

# Docker Engine 설치 (Desktop 아님 — 네이티브, 더 빠름)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# Docker Compose 설치
sudo apt install -y docker-compose-plugin
docker compose version  # 2.24+ 확인

# .NET 8 SDK 설치 (Blazor Server용)
wget https://dot.net/v1/dotnet-install.sh
chmod +x dotnet-install.sh
./dotnet-install.sh --channel 8.0
echo 'export DOTNET_ROOT=$HOME/.dotnet' >> ~/.bashrc
echo 'export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools' >> ~/.bashrc
source ~/.bashrc
dotnet --version  # 8.0.x 확인

# Miniconda 설치
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b
~/miniconda3/bin/conda init bash
source ~/.bashrc

# 작업 디렉토리
mkdir -p ~/quant-v31/{engine,dashboard,proto,scripts,data,models}
cd ~/quant-v31`}</Pre>

    <Sec c={C.cyan}>Step 1.2 — Docker Compose (PostgreSQL + TimescaleDB + Redis)</Sec>
    <Pre>{`# ~/quant-v31/docker-compose.yml
version: "3.9"
services:

  # ── PostgreSQL 16 + TimescaleDB ──
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: quant-postgres
    environment:
      POSTGRES_DB: quantdb
      POSTGRES_USER: quant
      POSTGRES_PASSWORD: "\${PG_PASSWORD:-QuantV31!Secure}"
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./scripts/init_db.sql:/docker-entrypoint-initdb.d/01_init.sql
    command: >
      postgres
        -c shared_preload_libraries='timescaledb'
        -c timescaledb.telemetry_level=off
        -c max_connections=100
        -c shared_buffers=8GB
        -c effective_cache_size=24GB
        -c work_mem=256MB
        -c maintenance_work_mem=2GB
        -c wal_buffers=64MB
    shm_size: '2g'
    restart: unless-stopped

  # ── Redis 7 (캐시 전용, 경량) ──
  redis:
    image: redis:7-alpine
    container_name: quant-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
    restart: unless-stopped

  # ── Python 전략 엔진 ──
  engine:
    build: ./engine
    container_name: quant-engine
    ports:
      - "8000:8000"    # FastAPI
      - "50051:50051"  # gRPC
    depends_on:
      - postgres
      - redis
    volumes:
      - ./engine:/app
      - ./data:/data
      - ./models:/models
    environment:
      - PG_DSN=postgresql+psycopg://quant:\${PG_PASSWORD}@postgres:5432/quantdb
      - PG_ASYNC_DSN=postgresql+psycopg_async://quant:\${PG_PASSWORD}@postgres:5432/quantdb
      - REDIS_URL=redis://redis:6379
      - ALPACA_KEY=\${ALPACA_KEY}
      - ALPACA_SECRET=\${ALPACA_SECRET}
      - ANTHROPIC_KEY=\${ANTHROPIC_KEY}
      - HF_HOME=/models
    restart: unless-stopped

  # ── Blazor Server 대시보드 ──
  dashboard:
    build: ./dashboard
    container_name: quant-dashboard
    ports:
      - "5000:5000"    # Blazor Server
    depends_on:
      - engine
      - postgres
    environment:
      - ConnectionStrings__Default=Host=postgres;Database=quantdb;Username=quant;Password=\${PG_PASSWORD}
      - GrpcUrl=http://engine:50051
    restart: unless-stopped

volumes:
  pg_data:
  redis_data:`}</Pre>

    <Info c={C.orange} icon="⚡" title="PostgreSQL 튜닝 포인트 (Dell 32GB RAM)">
      <b>shared_buffers=8GB</b> (RAM의 25%) — 자주 접근하는 데이터 캐시<br />
      <b>effective_cache_size=24GB</b> (RAM의 75%) — OS 캐시 포함 쿼리 최적화<br />
      <b>work_mem=256MB</b> — 정렬/해시 조인 성능 (퀀트 쿼리에 중요)<br />
      <b>shm_size=2g</b> — Docker 공유메모리 (PG 필수)
    </Info>

    <Sec c={C.violet}>Step 1.3 — Python 환경 + 패키지 (1주차)</Sec>
    <Pre>{`# conda 환경
conda create -n quant-v31 python=3.11 -y
conda activate quant-v31

# ─── 핵심 패키지 ───
pip install polars pandas numpy scipy scikit-learn
pip install fastapi uvicorn grpcio grpcio-tools
pip install vectorbt lightgbm xgboost
pip install yfinance alpaca-py fredapi
pip install statsmodels pyarrow
pip install anthropic python-telegram-bot
pip install apscheduler pydantic-settings

# ─── ★ PostgreSQL 드라이버 (핵심 변경) ───
pip install "psycopg[binary]"        # psycopg3 (최신, 비동기 지원)
pip install "sqlalchemy[asyncio]"    # SQLAlchemy 2.0 비동기

# ─── V3.1 레짐/센티먼트 ───
pip install hmmlearn
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers
pip install shap praw plotly

# ─── FinBERT 사전 다운로드 ───
python -c "
from transformers import AutoTokenizer, AutoModelForSequenceClassification
AutoTokenizer.from_pretrained('ProsusAI/finbert')
AutoModelForSequenceClassification.from_pretrained('ProsusAI/finbert')
print('✅ FinBERT downloaded')
"

# ─── PostgreSQL 연결 테스트 ───
python -c "
import psycopg
conn = psycopg.connect('postgresql://quant:QuantV31!Secure@localhost:5432/quantdb')
cur = conn.execute('SELECT version()')
print(f'✅ PostgreSQL: {cur.fetchone()[0][:50]}')
cur = conn.execute('SELECT extversion FROM pg_extension WHERE extname=\\'timescaledb\\'')
print(f'✅ TimescaleDB: {cur.fetchone()[0]}')
conn.close()
"`}</Pre>

    <Sec c={C.emerald}>Step 1.4 — Pydantic 설정 (PostgreSQL 버전)</Sec>
    <Pre>{`# engine/config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ─── ★ PostgreSQL (MSSQL 대체) ───
    pg_dsn: str = "postgresql+psycopg://quant:pass@localhost:5432/quantdb"
    pg_async_dsn: str = "postgresql+psycopg_async://quant:pass@localhost:5432/quantdb"
    redis_url: str = "redis://localhost:6379"
    
    # ─── API Keys ───
    alpaca_key: str = ""
    alpaca_secret: str = ""
    alpaca_paper: bool = True
    anthropic_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    
    # ─── 유니버스 ───
    universe_min_mcap: float = 300e6
    universe_max_mcap: float = 10e9
    
    # ─── 레짐 ───
    hmm_n_states: int = 3
    hmm_lookback_days: int = 504
    hmm_retrain_interval: str = "monthly"
    regime_transition_speed: float = 0.3
    
    # ─── Kill Switch ───
    kill_level1: float = -0.10
    kill_level2: float = -0.15
    kill_level3: float = -0.20
    kill_cooldown_days: int = 30
    
    # ─── 포지션 사이징 ───
    risk_per_trade: float = 0.02
    atr_stop_multiplier: float = 2.0
    kelly_fraction: float = 0.5
    max_position_pct: float = 0.10
    max_sector_pct: float = 0.25
    
    # ─── Vol-Targeting ───
    vol_target: float = 0.15
    max_leverage: float = 1.3
    min_exposure: float = 0.3
    
    # ─── FinBERT ───
    finbert_model: str = "ProsusAI/finbert"
    finbert_batch_size: int = 32
    finbert_threshold: float = 0.7
    
    # ─── 백테스트 ───
    backtest_years: int = 15
    walk_forward_train: int = 36
    walk_forward_test: int = 6
    slippage_bps: float = 5.0
    
    class Config:
        env_file = ".env"`}</Pre>

    <Sec c={C.orange}>Step 1.5 — ★ PostgreSQL 데이터 저장소</Sec>
    <Pre>{`# engine/data/storage.py
"""PostgreSQL + TimescaleDB + Redis 통합 저장소"""
import psycopg
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import redis
import json

class PostgresStore:
    """PostgreSQL + TimescaleDB 메인 저장소"""
    
    def __init__(self, dsn: str):
        self.dsn = dsn
    
    def get_conn(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)
    
    def insert_ohlcv_batch(self, records: list[dict]):
        """일봉 데이터 벌크 INSERT (TimescaleDB hypertable)"""
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO daily_prices 
                        (time, symbol, open, high, low, close, volume, adj_close)
                    VALUES (%(time)s, %(symbol)s, %(open)s, %(high)s,
                            %(low)s, %(close)s, %(volume)s, %(adj_close)s)
                    ON CONFLICT (time, symbol) DO UPDATE SET
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """, records)
            conn.commit()
    
    def get_ohlcv(self, symbol: str, days: int = 504):
        """종목 일봉 조회 (TimescaleDB 최적화)"""
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT time, open, high, low, close, volume
                FROM daily_prices
                WHERE symbol = %s
                ORDER BY time DESC
                LIMIT %s
            """, (symbol, days)).fetchall()
        return rows
    
    def get_latest_regime(self):
        """최신 레짐 조회"""
        with self.get_conn() as conn:
            return conn.execute("""
                SELECT * FROM regime_history
                ORDER BY detected_at DESC LIMIT 1
            """).fetchone()
    
    def insert_regime(self, regime_data: dict):
        """레짐 상태 기록"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO regime_history 
                    (regime, bull_prob, sideways_prob, bear_prob,
                     confidence, previous_regime, is_transition)
                VALUES (%(regime)s, %(bull)s, %(sideways)s, %(bear)s,
                        %(confidence)s, %(prev)s, %(transition)s)
            """, regime_data)
            conn.commit()
    
    def query_timescale_agg(self, symbol: str, interval: str = "1 day",
                             days: int = 90):
        """TimescaleDB 시간 버킷 집계 (강력한 기능!)"""
        with self.get_conn() as conn:
            return conn.execute("""
                SELECT time_bucket(%s, time) AS bucket,
                    first(open, time) AS open,
                    max(high) AS high,
                    min(low) AS low,
                    last(close, time) AS close,
                    sum(volume) AS volume
                FROM daily_prices
                WHERE symbol = %s
                  AND time > now() - interval '%s days'
                GROUP BY bucket
                ORDER BY bucket
            """, (interval, symbol, days)).fetchall()

class RedisCache:
    """Redis — 실시간 캐시 전용 (경량)"""
    
    def __init__(self, url: str = "redis://localhost:6379"):
        self.r = redis.from_url(url)
    
    def set_regime(self, regime: dict, ttl: int = 3600):
        self.r.setex("current_regime", ttl, json.dumps(regime))
    
    def get_regime(self) -> dict | None:
        data = self.r.get("current_regime")
        return json.loads(data) if data else None
    
    def set_price(self, symbol: str, price: float):
        self.r.hset("latest_prices", symbol, price)
    
    def get_price(self, symbol: str) -> float | None:
        val = self.r.hget("latest_prices", symbol)
        return float(val) if val else None
    
    def cache_signals(self, signals: dict, ttl: int = 300):
        self.r.setex("current_signals", ttl, json.dumps(signals))`}</Pre>

    <Sec c={C.rose}>Step 1.6 — 데이터 수집 + HMM 프로토타입 (2~4주차)</Sec>
    <Pre>{`# engine/data/collector.py
import polars as pl
import yfinance as yf
from pathlib import Path

class DataCollector:
    """15년 히스토리 → PostgreSQL + Parquet 이중 저장"""
    
    def __init__(self, pg_store):
        self.pg = pg_store
        self.parquet_dir = Path("/data/parquet")
    
    def collect_ohlcv(self, symbols: list[str], period="15y"):
        """yfinance → Parquet 백업 + PostgreSQL 적재"""
        for batch in self._batch(symbols, 50):
            data = yf.download(batch, period=period,
                              group_by="ticker", threads=True)
            for sym in batch:
                try:
                    df = data[sym].dropna().reset_index()
                    if len(df) < 252: continue
                    
                    # Parquet 백업 (원시 데이터)
                    path = self.parquet_dir / f"ohlcv/{sym}.parquet"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    pl.from_pandas(df).write_parquet(path)
                    
                    # PostgreSQL + TimescaleDB 적재
                    records = [{
                        "time": row["Date"],
                        "symbol": sym,
                        "open": row["Open"],
                        "high": row["High"],
                        "low": row["Low"],
                        "close": row["Close"],
                        "volume": int(row["Volume"]),
                        "adj_close": row.get("Adj Close", row["Close"]),
                    } for _, row in df.iterrows()]
                    self.pg.insert_ohlcv_batch(records)
                except: pass
    
    def collect_spy_vix(self):
        """SPY + VIX (HMM 레짐 학습용)"""
        for sym in ["SPY", "^VIX"]:
            data = yf.download(sym, period="15y").reset_index()
            name = sym.replace("^", "")
            pl.from_pandas(data).write_parquet(
                self.parquet_dir / f"benchmark/{name}.parquet")
    
    def _batch(self, lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

# ── HMM 프로토타입 (Phase 1에서 검증) ──
# engine/risk/regime.py (프로토타입 동일, SPY 데이터 소스만 PG로)
# → 코드는 V3.1 전략 설계서와 동일하므로 생략
# → 핵심: SPY 15년 데이터로 fit → 2020 COVID Bear 감지 확인`}</Pre>

    <Sec c={C.emerald}>Phase 1 체크리스트</Sec>
    <Chk items={[
      "Ubuntu 24.04 LTS 설치 + 초기 설정 (Docker, .NET 8, conda)",
      "docker compose up → PostgreSQL + TimescaleDB + Redis 정상 가동",
      "TimescaleDB hypertable 생성 확인 (daily_prices, regime_history 등)",
      "Python 환경 + 전체 패키지 설치 (psycopg3, hmmlearn, transformers, torch)",
      "psycopg3 → PostgreSQL 연결 테스트 성공",
      "FinBERT 모델 다운로드 + CPU 벤치마크 (초당 10건+ 목표)",
      "3,000+ 종목 15년 OHLCV → Parquet + PostgreSQL 이중 적재",
      "SPY + VIX 15년 벤치마크 데이터 저장",
      "FRED 매크로 7개 지표 수집 (장단기 스프레드 포함)",
      "Reddit/WSB 수집기 테스트 (PRAW)",
      "★ HMM 프로토타입: 2020 COVID Bear 정확히 감지 확인",
      "Alpaca Paper $100K 연동 + 테스트 주문",
      "Redis 캐시 동작 확인 (레짐, 가격)",
    ]} />
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// TAB 3: PHASE 2
// ═══════════════════════════════════════════════════════════════
function Phase2() {
  return (<div>
    <Info c={C.violet} icon="📊" title="Phase 2: 레짐 엔진 + 5대 전략 + 리스크 모듈 (5~14개월)">
      개발 순서: HMM 레짐(선행) → Kill Switch + ATR 사이징(선행) → ① Low-Vol → ④ Vol-Target → ② 모멘텀 → ⑤ FinBERT → ③ 페어즈. 모든 전략은 PostgreSQL에서 데이터를 읽고 결과를 기록.
    </Info>

    <Sec c={C.rose}>Step 2.1 — HMM 레짐 엔진 (5~6개월, ★ 선행 필수)</Sec>
    <Pre>{`# engine/risk/regime.py (PostgreSQL 연동 완성본)
from hmmlearn.hmm import GaussianHMM
import numpy as np
import pickle
from pathlib import Path

class RegimeDetector:
    """HMM 3-State 레짐 감지 (PostgreSQL 연동)"""
    
    MODEL_PATH = Path("/data/models/hmm_regime.pkl")
    
    def __init__(self, pg_store, n_states=3, lookback=504):
        self.pg = pg_store
        self.n_states = n_states
        self.lookback = lookback
        self.model = None
        self.state_map = {}
    
    def prepare_features(self):
        """PostgreSQL에서 SPY + VIX 데이터 로드 → 관측 변수"""
        spy_rows = self.pg.get_ohlcv("SPY", self.lookback)
        prices = np.array([r["close"] for r in reversed(spy_rows)])
        
        ret = np.diff(prices) / prices[:-1]
        # 21일 롤링 변동성
        vol = np.array([np.std(ret[max(0,i-21):i])*np.sqrt(252) 
                        for i in range(21, len(ret))])
        ret = ret[21:]
        
        n = min(len(ret), len(vol))
        X = np.column_stack([ret[-n:], vol[-n:]])
        return X[~np.isnan(X).any(axis=1)]
    
    def fit(self):
        X = self.prepare_features()
        self.model = GaussianHMM(
            n_components=self.n_states, covariance_type="full",
            n_iter=300, random_state=42, tol=0.001)
        self.model.fit(X)
        
        means = self.model.means_[:, 0]
        idx = np.argsort(means)[::-1]
        self.state_map = {idx[0]:"bull",idx[1]:"sideways",idx[2]:"bear"}
        self.save()
        return self
    
    def predict_current(self) -> dict:
        X = self.prepare_features()
        _, posteriors = self.model.score_samples(X)
        p = posteriors[-1]
        result = {self.state_map[i]: float(p[i]) for i in self.state_map}
        result["current"] = max(result, key=result.get)
        result["confidence"] = float(max(p))
        return result
    
    def save(self):
        self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.MODEL_PATH, "wb") as f:
            pickle.dump({"model":self.model,"map":self.state_map}, f)
    
    def load(self):
        with open(self.MODEL_PATH, "rb") as f:
            d = pickle.load(f)
            self.model, self.state_map = d["model"], d["map"]
        return self`}</Pre>

    <Sec c={C.orange}>Step 2.2 — Kill Switch + ATR 사이징 (6~7개월)</Sec>
    <Info c={C.orange} icon="🛡️" title="코드 변경 없음">
      Kill Switch와 Dynamic Position Sizer는 순수 Python 로직이므로 DB 변경에 영향 없습니다. V3.1 전략 설계서의 코드를 그대로 사용합니다.
      <br />• <b>kill_switch.py</b> — 3단계 (MDD -10%/-15%/-20%) 방어
      <br />• <b>position_sizer.py</b> — ATR + Vol역가중 + Kelly Half + 집중 하이브리드
    </Info>

    <Sec c={C.blue}>Step 2.3 — 전략 베이스 (PostgreSQL 연동)</Sec>
    <Pre>{`# engine/strategies/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Signal:
    symbol: str
    direction: str    # "long", "short", "close"
    strength: float   # -1.0 ~ 1.0
    strategy: str
    regime: str
    timestamp: str

class BaseStrategy(ABC):
    """V3.1 전략 기본 클래스 — PostgreSQL 연동"""
    
    def __init__(self, pg_store, config: dict):
        self.pg = pg_store    # ★ PostgreSQL 저장소
        self.config = config
        self.name = self.__class__.__name__
    
    @abstractmethod
    def generate_signals(self, regime: str,
                         regime_conf: float) -> list[Signal]:
        """DB에서 직접 데이터 읽어 시그널 생성"""
        pass
    
    def get_universe(self, min_mcap=300e6, max_mcap=10e9):
        """PostgreSQL에서 유니버스 조회"""
        with self.pg.get_conn() as conn:
            rows = conn.execute("""
                SELECT ticker FROM symbols
                WHERE market_cap BETWEEN %s AND %s
                  AND is_active = true
            """, (min_mcap, max_mcap)).fetchall()
        return [r["ticker"] for r in rows]
    
    def get_prices(self, symbol, days=504):
        """TimescaleDB에서 가격 조회"""
        return self.pg.get_ohlcv(symbol, days)
    
    def record_signals(self, signals: list[Signal]):
        """시그널을 DB에 기록"""
        with self.pg.get_conn() as conn:
            for s in signals:
                conn.execute("""
                    INSERT INTO signal_log 
                        (symbol, direction, strength, strategy, regime)
                    VALUES (%s, %s, %s, %s, %s)
                """, (s.symbol, s.direction, s.strength,
                      s.strategy, s.regime))
            conn.commit()`}</Pre>

    <Sec c={C.emerald}>Step 2.4 — ① Low-Vol + Quality (7~9개월)</Sec>
    <Pre>{`# engine/strategies/lowvol_quality.py
import numpy as np

class LowVolQuality(BaseStrategy):
    """저변동성+퀄리티 — PostgreSQL에서 데이터 직접 조회"""
    
    def generate_signals(self, regime, regime_conf):
        universe = self.get_universe()
        
        # TimescaleDB 집계 쿼리로 변동성 계산 (매우 빠름!)
        with self.pg.get_conn() as conn:
            factors = conn.execute("""
                WITH vol AS (
                    SELECT symbol,
                        stddev(daily_return) * sqrt(252) AS volatility
                    FROM (
                        SELECT symbol,
                            (close - lag(close) OVER (PARTITION BY symbol ORDER BY time))
                            / lag(close) OVER (PARTITION BY symbol ORDER BY time) AS daily_return
                        FROM daily_prices
                        WHERE time > now() - interval '252 days'
                          AND symbol = ANY(%s)
                    ) sub
                    GROUP BY symbol
                ),
                quality AS (
                    SELECT ticker AS symbol, roe, debt_to_equity, free_cashflow,
                        (roe - avg(roe) OVER()) / nullif(stddev(roe) OVER(), 0) +
                        (avg(debt_to_equity) OVER() - debt_to_equity) 
                            / nullif(stddev(debt_to_equity) OVER(), 0) +
                        (free_cashflow - avg(free_cashflow) OVER()) 
                            / nullif(stddev(free_cashflow) OVER(), 0)
                        AS quality_z
                    FROM fundamentals
                    WHERE ticker = ANY(%s)
                )
                SELECT v.symbol, v.volatility, q.quality_z
                FROM vol v JOIN quality q ON v.symbol = q.symbol
                WHERE v.volatility <= (
                    SELECT percentile_cont(0.30) WITHIN GROUP (ORDER BY volatility) FROM vol)
                  AND q.quality_z >= (
                    SELECT percentile_cont(0.70) WITHIN GROUP (ORDER BY quality_z) FROM quality)
                ORDER BY q.quality_z DESC
            """, (universe, universe)).fetchall()
        
        n = {"bull": 15, "sideways": 20, "bear": 25}.get(regime, 20)
        
        return [Signal(r["symbol"], "long", float(r["quality_z"]),
                       self.name, regime, "")
                for r in factors[:n]]`}</Pre>

    <Info c={C.cyan} icon="⚡" title="PostgreSQL + TimescaleDB 장점">
      변동성, 퀄리티 z-score 계산을 <b>SQL 한 방</b>으로 처리. Python에서 데이터를 가져와 계산하는 것보다 <b>5~10x 빠릅니다.</b> Window Function + CTE + TimescaleDB time_bucket의 조합이 퀀트에 매우 강력합니다.
    </Info>

    <Sec c={C.violet}>Step 2.5~2.8 — 나머지 전략 (8~14개월)</Sec>
    <Info c={C.violet} icon="📝" title="② 모멘텀, ③ 페어즈, ④ Vol-Targeting, ⑤ FinBERT">
      로직은 V3.1 전략 설계서와 동일합니다. 변경점은 데이터 소스만:<br />
      • <code>load_parquet()</code> → <code>self.pg.get_ohlcv()</code><br />
      • <code>pl.read_parquet()</code> → PostgreSQL CTE 쿼리<br />
      • 시그널 결과 → <code>self.record_signals()</code>로 DB 기록<br />
      <br />
      특히 ③ 페어즈의 공적분 쌍 탐색은 <b>PostgreSQL 물리뷰(materialized view)</b>로 캐싱하면 매번 재계산하지 않아도 됩니다.
    </Info>
    <Pre>{`-- 페어즈 쌍 탐색용 물리뷰 (주 1회 REFRESH)
CREATE MATERIALIZED VIEW mv_sector_correlations AS
SELECT a.symbol AS sym1, b.symbol AS sym2,
    corr(a.close, b.close) AS correlation,
    s.sector
FROM daily_prices a
JOIN daily_prices b ON a.time = b.time AND a.symbol < b.symbol
JOIN symbols s ON a.symbol = s.ticker
JOIN symbols s2 ON b.symbol = s2.ticker AND s.sector = s2.sector
WHERE a.time > now() - interval '252 days'
GROUP BY a.symbol, b.symbol, s.sector
HAVING corr(a.close, b.close) > 0.7;

-- 주 1회 갱신
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sector_correlations;`}</Pre>

    <Sec c={C.lime}>Phase 2 체크리스트</Sec>
    <Tbl headers={["기간","모듈","상태"]}
      colors={[C.tm, C.tb, C.emerald]}
      rows={[
        ["5~6월","HMM 레짐 엔진 (PG 연동) + 15년 검증","★ 선행"],
        ["6~7월","Kill Switch 3단계 + ATR 사이징","★ 선행"],
        ["7~9월","① Low-Vol+Quality (SQL 팩터 계산)","시작"],
        ["9~10월","④ Vol-Targeting (레짐 스케일)","오버레이"],
        ["10~11월","② Vol-Managed 모멘텀","공격"],
        ["11~12월","⑤ FinBERT 하이브리드","센티먼트"],
        ["12~14월","③ 페어즈 (물리뷰 + 공적분)","최고난이도"],
      ]} />
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// TAB 4: PHASE 3
// ═══════════════════════════════════════════════════════════════
function Phase3() {
  return (<div>
    <Info c={C.amber} icon="🏗️" title="Phase 3: 시스템 통합 + Blazor Server 대시보드 (15~18개월)">
      8단계 파이프라인 오케스트레이터 + ★ Blazor Server 대시보드 (Linux 완벽 동작, 브라우저 접속) + gRPC + SignalR 실시간 + systemd 서비스
    </Info>

    <Sec c={C.amber}>Step 3.1 — 오케스트레이터 (PostgreSQL 통합)</Sec>
    <Pre>{`# engine/api/main.py
from fastapi import FastAPI
from engine.data.storage import PostgresStore, RedisCache
from engine.risk.regime import RegimeDetector
from engine.risk.regime_allocator import RegimeAllocator
from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel
from engine.risk.position_sizer import DynamicPositionSizer

app = FastAPI(title="Quant V3.1 Engine")
pg = PostgresStore("postgresql+psycopg://quant:pass@postgres/quantdb")
cache = RedisCache("redis://redis:6379")

class PortfolioOrchestrator:
    def __init__(self):
        self.regime_detector = RegimeDetector(pg).load()
        self.allocator = RegimeAllocator(self.regime_detector)
        self.kill_switch = DrawdownKillSwitch()
        self.sizer = DynamicPositionSizer()
        self.strategies = {
            "LowVolQuality": LowVolQuality(pg, config),
            "VolManagedMomentum": VolManagedMomentum(pg, config),
            "PairsTrading": PairsTrading(pg, config),
        }
    
    def execute_daily(self):
        """=== 일일 8단계 파이프라인 ==="""
        
        # 1) 레짐 감지 (PostgreSQL에서 SPY 데이터)
        regime = self.regime_detector.predict_current()
        cache.set_regime(regime)  # Redis 캐시
        pg.insert_regime(regime)  # DB 기록
        
        # 2) Kill Switch
        pv = self.executor.get_portfolio_value()
        kill = self.kill_switch.update(pv)
        if kill == DefenseLevel.EMERGENCY:
            self._emergency_liquidate()
            return
        
        # 3) 레짐별 배분
        alloc = self.allocator.get_allocation(regime)
        exp_limit = self.kill_switch.get_exposure_limit()
        
        # 4) 전략 시그널 (각 전략이 PG에서 직접 조회)
        signals = {}
        allowed = self.kill_switch.get_allowed_strategies()
        for name, strat in self.strategies.items():
            if "all" in allowed or name in allowed:
                sigs = strat.generate_signals(
                    regime["current"], regime["confidence"])
                signals[name] = sigs
        
        # 5) 센티먼트 오버레이
        # 6) Vol-Targeting
        # 7) ATR 사이징
        # 8) VWAP 실행
        
        # 결과 기록 → PostgreSQL
        self._record_snapshot(pv, regime, kill)
    
    def _record_snapshot(self, value, regime, kill):
        with pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO portfolio_snapshots
                    (total_value, regime, regime_confidence,
                     kill_level, exposure_limit)
                VALUES (%s, %s, %s, %s, %s)
            """, (value, regime["current"], regime["confidence"],
                  kill.name, self.kill_switch.get_exposure_limit()))
            conn.commit()`}</Pre>

    <Sec c={C.cyan}>Step 3.2 — ★ Blazor Server 프로젝트 생성</Sec>
    <Pre>{`# Ubuntu에서 Blazor Server 프로젝트 생성
cd ~/quant-v31/dashboard
dotnet new blazor -n QuantDashboard --interactivity Server
cd QuantDashboard

# ★ NuGet 패키지 설치
dotnet add package Npgsql --version 8.0.6
dotnet add package Npgsql.EntityFrameworkCore.PostgreSQL --version 8.0.10
dotnet add package Grpc.Net.Client --version 2.67.0
dotnet add package Google.Protobuf --version 3.28.3
dotnet add package Grpc.Tools --version 2.67.0
dotnet add package DevExpress.Blazor --version 24.1.6

# 실행 테스트
dotnet run --urls "http://0.0.0.0:5000"
# → 브라우저에서 http://서버IP:5000 접속`}</Pre>

    <Sec c={C.violet}>Step 3.3 — Blazor Server: PostgreSQL 서비스</Sec>
    <Pre>{`// dashboard/QuantDashboard/Services/PostgresService.cs
using Npgsql;

public class PostgresService
{
    private readonly string _connStr;
    
    public PostgresService(IConfiguration config)
    {
        _connStr = config.GetConnectionString("Default");
    }
    
    // ─── 레짐 현황 조회 ───
    public async Task<RegimeState> GetCurrentRegimeAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        
        await using var cmd = new NpgsqlCommand(@"
            SELECT regime, bull_prob, sideways_prob, bear_prob,
                   confidence, detected_at
            FROM regime_history
            ORDER BY detected_at DESC LIMIT 1", conn);
        
        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
        {
            return new RegimeState
            {
                Current = reader.GetString(0),
                BullProb = reader.GetDouble(1),
                SidewaysProb = reader.GetDouble(2),
                BearProb = reader.GetDouble(3),
                Confidence = reader.GetDouble(4),
                DetectedAt = reader.GetDateTime(5)
            };
        }
        return new RegimeState { Current = "unknown" };
    }
    
    // ─── Kill Switch 현황 ───
    public async Task<KillSwitchState> GetKillSwitchAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        
        await using var cmd = new NpgsqlCommand(@"
            SELECT to_level, current_mdd, exposure_limit, cooldown_until
            FROM kill_switch_log
            ORDER BY event_time DESC LIMIT 1", conn);
        
        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
        {
            return new KillSwitchState
            {
                Level = reader.GetString(0),
                CurrentMdd = reader.GetDouble(1),
                ExposureLimit = reader.GetDouble(2),
            };
        }
        return new KillSwitchState { Level = "NORMAL" };
    }
    
    // ─── 포트폴리오 성과 (TimescaleDB 집계) ───
    public async Task<List<DailySnapshot>> GetPerformanceAsync(int days = 90)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        
        await using var cmd = new NpgsqlCommand($@"
            SELECT snapshot_date, total_value, daily_return,
                   sharpe_ratio, max_drawdown, regime, kill_level
            FROM portfolio_snapshots
            WHERE snapshot_date > now() - interval '{days} days'
            ORDER BY snapshot_date", conn);
        
        var results = new List<DailySnapshot>();
        await using var reader = await cmd.ExecuteReaderAsync();
        while (await reader.ReadAsync())
        {
            results.Add(new DailySnapshot {
                Date = reader.GetDateTime(0),
                TotalValue = reader.GetDouble(1),
                DailyReturn = reader.GetDouble(2),
                Sharpe = reader.IsDBNull(3) ? 0 : reader.GetDouble(3),
                MaxDrawdown = reader.IsDBNull(4) ? 0 : reader.GetDouble(4),
                Regime = reader.GetString(5),
                KillLevel = reader.GetString(6),
            });
        }
        return results;
    }
}

// ─── Data Models ───
public record RegimeState
{
    public string Current { get; init; }
    public double BullProb { get; init; }
    public double SidewaysProb { get; init; }
    public double BearProb { get; init; }
    public double Confidence { get; init; }
    public DateTime DetectedAt { get; init; }
}

public record KillSwitchState
{
    public string Level { get; init; }
    public double CurrentMdd { get; init; }
    public double ExposureLimit { get; init; }
}

public record DailySnapshot
{
    public DateTime Date { get; init; }
    public double TotalValue { get; init; }
    public double DailyReturn { get; init; }
    public double Sharpe { get; init; }
    public double MaxDrawdown { get; init; }
    public string Regime { get; init; }
    public string KillLevel { get; init; }
}`}</Pre>

    <Sec c={C.pink}>Step 3.4 — Blazor Server: 레짐 대시보드 페이지</Sec>
    <Pre>{`@* dashboard/QuantDashboard/Components/Pages/Regime.razor *@
@page "/regime"
@inject PostgresService Db
@inject GrpcClient Grpc
@rendermode InteractiveServer

<h3>🎯 시장 레짐 모니터</h3>

@if (regime != null)
{
    <div class="regime-gauge">
        <div class="regime-card @GetRegimeClass()">
            <h2>@regime.Current.ToUpper()</h2>
            <p>신뢰도: @(regime.Confidence.ToString("P0"))</p>
            <p>감지 시각: @regime.DetectedAt.ToString("yyyy-MM-dd HH:mm")</p>
        </div>
        
        <div class="probabilities">
            <div class="bar bull" style="width:@(regime.BullProb*100)%">
                🟢 Bull @(regime.BullProb.ToString("P1"))
            </div>
            <div class="bar sideways" style="width:@(regime.SidewaysProb*100)%">
                🟡 Sideways @(regime.SidewaysProb.ToString("P1"))
            </div>
            <div class="bar bear" style="width:@(regime.BearProb*100)%">
                🔴 Bear @(regime.BearProb.ToString("P1"))
            </div>
        </div>
    </div>
    
    @if (killSwitch != null)
    {
        <div class="kill-switch-panel @GetKillClass()">
            <h4>🛡️ Kill Switch: @killSwitch.Level</h4>
            <p>현재 MDD: @(killSwitch.CurrentMdd.ToString("P2"))</p>
            <p>Exposure 한도: @(killSwitch.ExposureLimit.ToString("P0"))</p>
        </div>
    }
}

@code {
    private RegimeState? regime;
    private KillSwitchState? killSwitch;
    
    protected override async Task OnInitializedAsync()
    {
        regime = await Db.GetCurrentRegimeAsync();
        killSwitch = await Db.GetKillSwitchAsync();
    }
    
    private string GetRegimeClass() => regime?.Current switch
    {
        "bull" => "regime-bull",
        "bear" => "regime-bear",
        _ => "regime-sideways"
    };
    
    private string GetKillClass() => killSwitch?.Level switch
    {
        "EMERGENCY" => "kill-emergency",
        "DEFENSIVE" => "kill-defensive",
        "WARNING" => "kill-warning",
        _ => "kill-normal"
    };
}`}</Pre>

    <Sec c={C.orange}>Step 3.5 — ★ systemd 서비스 (Ubuntu 자동 관리)</Sec>
    <Pre>{`# systemd/quant-engine.service
[Unit]
Description=Quant V3.1 Python Engine
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=quant
WorkingDirectory=/home/quant/quant-v31
ExecStart=/home/quant/miniconda3/envs/quant-v31/bin/uvicorn \\
    engine.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target

# systemd/quant-dashboard.service
[Unit]
Description=Quant V3.1 Blazor Server Dashboard
After=quant-engine.service

[Service]
Type=simple
User=quant
WorkingDirectory=/home/quant/quant-v31/dashboard/QuantDashboard
ExecStart=/home/quant/.dotnet/dotnet run --urls "http://0.0.0.0:5000"
Restart=always
RestartSec=10
Environment=DOTNET_ENVIRONMENT=Production

[Install]
WantedBy=multi-user.target

# ─── 설치 & 관리 ───
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable quant-engine quant-dashboard
sudo systemctl start quant-engine quant-dashboard

# 상태 확인
sudo systemctl status quant-engine
sudo systemctl status quant-dashboard

# 로그 확인
journalctl -u quant-engine -f
journalctl -u quant-dashboard -f`}</Pre>

    <Sec c={C.emerald}>Phase 3 체크리스트</Sec>
    <Chk c={C.amber} items={[
      "8단계 오케스트레이터 (레짐→Kill→배분→시그널→센티먼트→Vol→사이징→VWAP)",
      "모든 전략이 PostgreSQL에서 직접 데이터 조회 + 결과 기록",
      "Blazor Server 프로젝트 생성 + Npgsql 연동",
      "레짐 게이지 + Kill Switch 패널 Razor 페이지",
      "gRPC Python↔C# 연동 정상 동작",
      "SignalR 실시간 푸시 (레짐 변경 시 즉시 갱신)",
      "systemd 서비스 등록 (engine + dashboard 자동 시작)",
      "브라우저에서 http://서버IP:5000 접속 확인",
      "APScheduler 전체 스케줄 자동 실행 테스트",
      "Telegram 알림 (레짐 전환, Kill Switch, 매매 완료)",
    ]} />
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// TAB 5: PHASE 4
// ═══════════════════════════════════════════════════════════════
function Phase4() {
  return (<div>
    <Info c={C.pink} icon="🧪" title="Phase 4: 백테스트 검증 + Paper Trading (19~30개월)">
      Walk-Forward + DSR + Monte Carlo + 레짐 전환 스트레스 + Kill Switch 검증 + Granger 센티먼트. 전부 PostgreSQL에서 데이터를 읽어 수행.
    </Info>

    <Sec c={C.pink}>백테스트: PostgreSQL 활용 팁</Sec>
    <Pre>{`-- TimescaleDB의 강력한 기능: 연속 집계 (Continuous Aggregate)
-- 일봉 데이터를 자동으로 주봉/월봉으로 집계

CREATE MATERIALIZED VIEW weekly_prices
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 week', time) AS week,
    symbol,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM daily_prices
GROUP BY week, symbol;

-- 정책: 7일 지나면 자동 갱신
SELECT add_continuous_aggregate_policy('weekly_prices',
    start_offset => interval '30 days',
    end_offset => interval '1 day',
    schedule_interval => interval '1 day');

-- 백테스트 쿼리 예: 12개월 모멘텀 계산 (SQL 한 방)
SELECT symbol,
    (last_close / first_close - 1) AS mom_12m,
    (last_close / lag_1m - 1) AS mom_1m
FROM (
    SELECT symbol,
        last(close, time) AS last_close,
        first(close, time) AS first_close,
        last(close, time) FILTER (WHERE time < now()-interval '21 days')
            AS lag_1m
    FROM daily_prices
    WHERE time > now() - interval '252 days'
    GROUP BY symbol
) sub;`}</Pre>

    <Sec c={C.rose}>레짐 전환 스트레스 + GO/STOP 기준</Sec>
    <Info c={C.rose} icon="⚠️" title="코드 로직 동일">
      레짐 스트레스(COVID/금리/회복/VIX), Walk-Forward, DSR, Monte Carlo, Granger 테스트의 <b>Python 로직은 V3.1 전략 설계서와 동일</b>합니다. 데이터 소스만 Parquet → PostgreSQL로 변경.
    </Info>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, margin: "10px 0" }}>
      <Card accent={C.emerald}>
        <div style={{ color: C.emerald, fontWeight: 800, fontSize: 13, marginBottom: 8 }}>✅ GO (전부 충족)</div>
        <Chk c={C.emerald} items={[
          "Paper 9개월+ 운용",
          "OOS Sharpe > 1.1",
          "MDD < -18%",
          "DSR > 95%",
          "HMM 오탐률 < 15%",
          "Kill Switch 정상 발동",
          "레짐 스트레스 4건 통과",
          "센티먼트 Granger 유의",
        ]} />
      </Card>
      <Card accent={C.rose}>
        <div style={{ color: C.rose, fontWeight: 800, fontSize: 13, marginBottom: 8 }}>❌ STOP (하나라도)</div>
        <Chk c={C.rose} items={[
          "MDD -20% 도달",
          "Sharpe < 0.8 연속 3개월",
          "DSR < 80%",
          "HMM 오탐률 > 25%",
          "Kill Switch 미작동",
          "시스템 오류 비정상 거래",
        ]} />
      </Card>
    </div>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// TAB 6: DATABASE
// ═══════════════════════════════════════════════════════════════
function Database() {
  return (<div>
    <Info c={C.cyan} icon="🐘" title="PostgreSQL 16 + TimescaleDB 스키마 설계">
      MSSQL → PostgreSQL 전면 변환. TimescaleDB hypertable로 시계열 자동 관리(압축, 파티셔닝, 연속집계). JSONB로 유연한 메타데이터 저장.
    </Info>

    <Sec c={C.cyan}>init_db.sql — 전체 스키마</Sec>
    <Pre>{`-- scripts/init_db.sql
-- PostgreSQL 16 + TimescaleDB

-- TimescaleDB 확장 활성화
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ═══════════════════════════════════
-- 1. 종목 마스터
-- ═══════════════════════════════════
CREATE TABLE symbols (
    symbol_id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    company_name VARCHAR(200),
    sector VARCHAR(50),
    industry VARCHAR(100),
    market_cap NUMERIC(18,2),
    exchange VARCHAR(10),
    is_active BOOLEAN DEFAULT true,
    meta JSONB DEFAULT '{}',        -- ★ 유연한 메타데이터
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_symbols_sector ON symbols(sector);
CREATE INDEX idx_symbols_active ON symbols(is_active) WHERE is_active;

-- ═══════════════════════════════════
-- 2. 일봉 가격 (★ TimescaleDB Hypertable)
-- ═══════════════════════════════════
CREATE TABLE daily_prices (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    open NUMERIC(12,4),
    high NUMERIC(12,4),
    low NUMERIC(12,4),
    close NUMERIC(12,4),
    volume BIGINT,
    adj_close NUMERIC(12,4),
    UNIQUE(time, symbol)
);
-- ★ TimescaleDB Hypertable 변환 (자동 시간 파티셔닝)
SELECT create_hypertable('daily_prices', by_range('time'));

-- ★ 자동 압축 정책: 30일 지난 데이터 자동 압축 (70% 용량 절감)
ALTER TABLE daily_prices SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('daily_prices', interval '30 days');

-- ═══════════════════════════════════
-- 3. 재무 데이터
-- ═══════════════════════════════════
CREATE TABLE fundamentals (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES symbols(ticker),
    report_date DATE DEFAULT CURRENT_DATE,
    market_cap NUMERIC(18,2),
    roe NUMERIC(8,4),
    revenue_growth NUMERIC(8,4),
    eps NUMERIC(10,4),
    debt_to_equity NUMERIC(8,4),
    free_cashflow NUMERIC(18,2),
    gross_margin NUMERIC(8,4),
    beta NUMERIC(6,4),
    extra JSONB DEFAULT '{}',       -- ★ 추가 지표 유연 저장
    UNIQUE(ticker, report_date)
);

-- ═══════════════════════════════════
-- 4. 거래 기록
-- ═══════════════════════════════════
CREATE TABLE trades (
    trade_id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(50),
    symbol VARCHAR(10),
    strategy VARCHAR(50),
    side VARCHAR(5),
    qty NUMERIC(12,4),
    price NUMERIC(12,4),
    slippage NUMERIC(10,6),
    commission NUMERIC(10,4),
    regime VARCHAR(10),
    kill_level VARCHAR(15),
    executed_at TIMESTAMPTZ DEFAULT now(),
    is_paper BOOLEAN DEFAULT true,
    meta JSONB DEFAULT '{}'
);
CREATE INDEX idx_trades_time ON trades(executed_at);
CREATE INDEX idx_trades_strategy ON trades(strategy);

-- ═══════════════════════════════════
-- 5. 포트폴리오 스냅샷 (★ Hypertable)
-- ═══════════════════════════════════
CREATE TABLE portfolio_snapshots (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_value NUMERIC(18,2),
    cash_value NUMERIC(18,2),
    daily_return NUMERIC(10,6),
    cumulative_return NUMERIC(10,6),
    sharpe_ratio NUMERIC(6,4),
    max_drawdown NUMERIC(6,4),
    calmar_ratio NUMERIC(6,4),
    vol_scale NUMERIC(4,2),
    regime VARCHAR(10),
    regime_confidence NUMERIC(4,3),
    kill_level VARCHAR(15),
    exposure_limit NUMERIC(4,2),
    dsr_score NUMERIC(6,4)
);
SELECT create_hypertable('portfolio_snapshots', by_range('time'));

-- ═══════════════════════════════════
-- 6. ★ 레짐 히스토리 (Hypertable)
-- ═══════════════════════════════════
CREATE TABLE regime_history (
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    regime VARCHAR(10),
    bull_prob NUMERIC(5,4),
    sideways_prob NUMERIC(5,4),
    bear_prob NUMERIC(5,4),
    confidence NUMERIC(5,4),
    previous_regime VARCHAR(10),
    is_transition BOOLEAN DEFAULT false
);
SELECT create_hypertable('regime_history', by_range('detected_at'));

-- ═══════════════════════════════════
-- 7. ★ Kill Switch 로그
-- ═══════════════════════════════════
CREATE TABLE kill_switch_log (
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_level VARCHAR(15),
    to_level VARCHAR(15),
    current_mdd NUMERIC(6,4),
    portfolio_value NUMERIC(18,2),
    exposure_limit NUMERIC(4,2),
    cooldown_until TIMESTAMPTZ
);
SELECT create_hypertable('kill_switch_log', by_range('event_time'));

-- ═══════════════════════════════════
-- 8. ★ 센티먼트 스코어 (Hypertable)
-- ═══════════════════════════════════
CREATE TABLE sentiment_scores (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol VARCHAR(10),
    finbert_score NUMERIC(5,3),
    claude_score NUMERIC(5,3),
    hybrid_score NUMERIC(5,3),
    source VARCHAR(20),
    headline_count INT,
    meta JSONB DEFAULT '{}'
);
SELECT create_hypertable('sentiment_scores', by_range('time'));

-- ═══════════════════════════════════
-- 9. 전략별 성과
-- ═══════════════════════════════════
CREATE TABLE strategy_performance (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy VARCHAR(50),
    daily_return NUMERIC(10,6),
    allocation NUMERIC(4,2),
    regime VARCHAR(10),
    signal_count INT,
    win_rate NUMERIC(4,2),
    profit_factor NUMERIC(6,2)
);
SELECT create_hypertable('strategy_performance', by_range('time'));

-- ═══════════════════════════════════
-- 10. 팩터 스코어
-- ═══════════════════════════════════
CREATE TABLE factor_scores (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol VARCHAR(10),
    volatility NUMERIC(8,6),
    quality_z NUMERIC(8,4),
    momentum_z NUMERIC(8,4),
    vol_scale NUMERIC(4,2),
    sentiment NUMERIC(4,3),
    composite NUMERIC(8,4)
);
SELECT create_hypertable('factor_scores', by_range('time'));

-- ═══════════════════════════════════
-- 11. 공적분 페어즈
-- ═══════════════════════════════════
CREATE TABLE cointegrated_pairs (
    pair_id SERIAL PRIMARY KEY,
    symbol1 VARCHAR(10),
    symbol2 VARCHAR(10),
    p_value NUMERIC(8,6),
    spread_zscore NUMERIC(6,2),
    is_active BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(symbol1, symbol2)
);

-- 12. 시그널 로그
CREATE TABLE signal_log (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol VARCHAR(10),
    direction VARCHAR(10),
    strength NUMERIC(6,3),
    strategy VARCHAR(50),
    regime VARCHAR(10)
);
SELECT create_hypertable('signal_log', by_range('time'));`}</Pre>

    <Sec c={C.violet}>핵심 뷰 + 연속 집계</Sec>
    <Pre>{`-- ★ 레짐별 전략 성과 (연속 집계 — 자동 갱신)
CREATE MATERIALIZED VIEW mv_regime_strategy_perf
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', time) AS day,
    strategy, regime,
    avg(daily_return) AS avg_return,
    stddev(daily_return) AS vol,
    count(*) AS obs
FROM strategy_performance
GROUP BY day, strategy, regime;

-- ★ 주봉 가격 (연속 집계)
CREATE MATERIALIZED VIEW weekly_prices
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 week', time) AS week,
    symbol,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM daily_prices
GROUP BY week, symbol;

-- 레짐 전환 요약
CREATE VIEW vw_regime_transitions AS
SELECT previous_regime, regime AS new_regime,
    count(*) AS count,
    avg(confidence) AS avg_confidence
FROM regime_history
WHERE is_transition = true
GROUP BY previous_regime, regime;

-- 최신 포트폴리오
CREATE VIEW vw_current_portfolio AS
SELECT * FROM portfolio_snapshots
ORDER BY time DESC LIMIT 1;`}</Pre>

    <Info c={C.lime} icon="🏆" title="MSSQL → PostgreSQL+TimescaleDB 핵심 장점 요약">
      <b>1. Hypertable 자동 파티셔닝:</b> 15년 일봉 데이터가 날짜별로 자동 분할, 쿼리 10x 빠름<br />
      <b>2. 자동 압축:</b> 30일 지난 데이터 70% 압축 → 1.5TB HDD 충분<br />
      <b>3. 연속 집계:</b> 주봉/월봉 자동 생성 → 백테스트에서 별도 계산 불필요<br />
      <b>4. JSONB:</b> symbols.meta, trades.meta에 유연한 메타데이터 저장<br />
      <b>5. Window Function:</b> 팩터 z-score, 모멘텀 계산을 SQL 한 방에<br />
      <b>6. 비용:</b> $0 (MSSQL Enterprise 라이센스 불필요)
    </Info>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// TAB 7: ROADMAP
// ═══════════════════════════════════════════════════════════════
function Roadmap() {
  return (<div>
    <Info c={C.lime} icon="🗺️" title="V3.1 Ubuntu Edition — 31개월+ 로드맵">
      Ubuntu + PostgreSQL + TimescaleDB + Blazor Server 기준. ★ = 인프라 변경 관련 항목.
    </Info>

    {[
      { phase: "Phase 1", period: "1~4개월", c: C.blue, title: "Ubuntu 환경 + PG/TimescaleDB + 데이터",
        items: [
          { m: "1주", t: "★ Ubuntu 24.04 초기 설정 (Docker Engine, .NET 8, conda)", s: "인프라" },
          { m: "1주", t: "★ docker compose up (PostgreSQL+TimescaleDB+Redis)", s: "인프라" },
          { m: "1주", t: "★ init_db.sql 실행 (hypertable, 압축, 연속집계)", s: "인프라" },
          { m: "1주", t: "Python 환경 + psycopg3 + 전체 패키지", s: "환경" },
          { m: "2~3주", t: "3,000종목 15년 OHLCV → Parquet + PostgreSQL 이중 적재", s: "데이터" },
          { m: "3주", t: "FRED 매크로 + Reddit + EDGAR 수집기", s: "데이터" },
          { m: "4주", t: "HMM 프로토타입 (PG에서 SPY 로드) + FinBERT 벤치마크", s: "검증" },
          { m: "4주", t: "Alpaca Paper $100K + Redis 캐시", s: "연동" },
        ]},
      { phase: "Phase 2", period: "5~14개월", c: C.violet, title: "레짐 + 5전략 + 리스크 (PostgreSQL 연동)",
        items: [
          { m: "5~6월", t: "HMM 레짐 엔진 (PG 직접 조회) + 15년 검증", s: "★ 선행" },
          { m: "6~7월", t: "Kill Switch + ATR 사이징 (로직 변경 없음)", s: "★ 선행" },
          { m: "7~9월", t: "① Low-Vol+Quality (★ SQL CTE로 팩터 계산)", s: "전략" },
          { m: "9~10월", t: "④ Vol-Targeting (레짐 스케일)", s: "오버레이" },
          { m: "10~11월", t: "② Vol-Managed 모멘텀", s: "전략" },
          { m: "11~12월", t: "⑤ FinBERT 하이브리드 + Claude 2차", s: "센티먼트" },
          { m: "12~14월", t: "③ 페어즈 (★ 물리뷰 mv_sector_correlations)", s: "최고난이도" },
        ]},
      { phase: "Phase 3", period: "15~18개월", c: C.amber, title: "통합 + ★ Blazor Server + systemd",
        items: [
          { m: "15월", t: "8단계 오케스트레이터 (PG 전체 연동)", s: "핵심" },
          { m: "16월", t: "★ Blazor Server 프로젝트 (Npgsql + SignalR)", s: "대시보드" },
          { m: "16월", t: "★ Regime.razor + Risk.razor 페이지", s: "대시보드" },
          { m: "17월", t: "gRPC + Telegram + SHAP 시각화", s: "연동" },
          { m: "17월", t: "★ systemd 서비스 등록 (자동 시작/재시작)", s: "인프라" },
          { m: "18월", t: "★ 브라우저 접속 테스트 (PC/모바일)", s: "검증" },
        ]},
      { phase: "Phase 4", period: "19~30개월", c: C.pink, title: "검증 + Paper 9~12개월",
        items: [
          { m: "19~20월", t: "Walk-Forward + DSR + Monte Carlo", s: "검증" },
          { m: "20~22월", t: "레짐 스트레스 4건 + Kill Switch + Granger", s: "검증" },
          { m: "22~30월", t: "Paper Trading $100K 연속 운용", s: "실전" },
          { m: "30월+", t: "GO 판정 → Live $5K~10K 소규모 전환", s: "전환" },
        ]},
    ].map((ph, pi) => (
      <div key={pi} style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <span style={{ background: `${ph.c}18`, color: ph.c, padding: "3px 10px",
            borderRadius: 6, fontSize: 11, fontWeight: 800, border: `1px solid ${ph.c}30` }}>
            {ph.phase}
          </span>
          <span style={{ color: C.tb, fontWeight: 700, fontSize: 13 }}>{ph.title}</span>
          <span style={{ color: C.tm, fontSize: 10 }}>({ph.period})</span>
        </div>
        {ph.items.map((it, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "60px 1fr 70px",
            gap: 6, padding: "4px 10px", fontSize: 11,
            background: i % 2 === 0 ? C.s1 : "transparent", borderRadius: 4, alignItems: "center" }}>
            <span style={{ color: ph.c, fontWeight: 700, fontFamily: "monospace", fontSize: 10 }}>{it.m}</span>
            <span style={{ color: it.s.includes("★") ? C.rose : C.t }}>{it.t}</span>
            <Tag c={it.s.includes("★") ? C.rose : it.s === "인프라" ? C.cyan : C.amber}>{it.s}</Tag>
          </div>
        ))}
      </div>
    ))}

    <Sec c={C.emerald}>성공 벤치마크</Sec>
    <Stat items={[
      { c: C.emerald, label: "목표 CAGR", value: "15~20%", sub: "레짐 평균" },
      { c: C.blue, label: "Sharpe", value: "1.3~1.9", sub: "레짐+Kill Switch" },
      { c: C.amber, label: "MDD", value: "<-18%", sub: "Kill Switch -20% 차단" },
      { c: C.violet, label: "인프라 비용", value: "$0", sub: "전부 오픈소스" },
    ]} />

    <Sec c={C.rose}>학술 참고문헌</Sec>
    {[
      "Hamilton (1989) — HMM 레짐 전환 모델 (Econometrica)",
      "Gupta et al. (2025) — 앙상블-HMM 시장 레짐 감지 (DSFE)",
      "Araci (2019) — FinBERT 금융 센티먼트 분석",
      "Bailey & López de Prado (2014) — Deflated Sharpe Ratio",
      "Barroso & Santa-Clara (2015) — Vol-Managed Momentum (JFE)",
      "Harvey et al. (2018) — Volatility Targeting (JPM)",
      "Gatev et al. (2006) — Pairs Trading",
      "López de Prado (2018) — Advances in Financial ML",
      "Ruan & Jiang (2025) — FinBERT+XGBoost 주가 예측",
    ].map((r, i) => (
      <div key={i} style={{ padding: "3px 0", fontSize: 10.5, color: C.t }}>
        <span style={{ color: C.tm, marginRight: 6 }}>[{i + 1}]</span>{r}
      </div>
    ))}
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════
const tabs = [
  { id: "overview", icon: "🐧", label: "전체 설계", c: C.emerald },
  { id: "p1", icon: "🔧", label: "Phase 1", c: C.blue },
  { id: "p2", icon: "📊", label: "Phase 2", c: C.violet },
  { id: "p3", icon: "🏗️", label: "Phase 3", c: C.amber },
  { id: "p4", icon: "🧪", label: "Phase 4", c: C.pink },
  { id: "db", icon: "🐘", label: "DB 설계", c: C.cyan },
  { id: "road", icon: "🗺️", label: "로드맵", c: C.lime },
];
const pages = {
  overview: Overview, p1: Phase1, p2: Phase2,
  p3: Phase3, p4: Phase4, db: Database, road: Roadmap,
};

export default function App() {
  const [active, setActive] = useState("overview");
  const Page = pages[active];
  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.t,
      fontFamily: "'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" }}>
      <link href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css" rel="stylesheet" />

      <div style={{ background: "linear-gradient(180deg,#0d0e1a,#05060b)",
        borderBottom: `1px solid ${C.bd}`, padding: "16px 16px 10px", textAlign: "center" }}>
        <div style={{ display: "flex", justifyContent: "center", gap: 6, marginBottom: 6 }}>
          <span style={{ background: `${C.orange}15`, color: C.orange, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.orange}30` }}>V3.1</span>
          <span style={{ background: `${C.cyan}15`, color: C.cyan, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.cyan}30` }}>UBUNTU</span>
          <span style={{ background: `${C.blue}15`, color: C.blue, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.blue}30` }}>PostgreSQL</span>
        </div>
        <h1 style={{ fontSize: 18, fontWeight: 900, margin: "2px 0",
          background: "linear-gradient(135deg,#f43f5e,#f59e0b,#10b981,#3b82f6,#8b5cf6)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          레짐 적응형 퀀트 시스템 구축 설계서
        </h1>
        <p style={{ color: C.tm, fontSize: 10, margin: 0 }}>
          Ubuntu 24.04 + PostgreSQL + TimescaleDB + Blazor Server | 단계별 구현 가이드
        </p>
      </div>

      <div style={{ display: "flex", overflowX: "auto", gap: 2, padding: "6px 8px",
        borderBottom: `1px solid ${C.bd}`, background: "#080a12" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActive(t.id)}
            style={{
              background: active === t.id ? `${t.c}15` : "transparent",
              border: active === t.id ? `1px solid ${t.c}30` : "1px solid transparent",
              borderRadius: 7, padding: "5px 9px", cursor: "pointer",
              color: active === t.id ? t.c : C.tm,
              fontSize: 11, fontWeight: active === t.id ? 700 : 500,
              whiteSpace: "nowrap", fontFamily: "inherit",
            }}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      <div style={{ padding: "10px 12px", maxWidth: 880, margin: "0 auto" }}>
        <Page />
      </div>

      <div style={{ textAlign: "center", padding: "14px", borderTop: `1px solid ${C.bd}`,
        color: "#333846", fontSize: 9 }}>
        Quant V3.1 Ubuntu Ed. | PostgreSQL+TimescaleDB | Blazor Server | 4 LLM 통합
      </div>
    </div>
  );
}
