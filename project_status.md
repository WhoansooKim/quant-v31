# Quant V3.1 Project Status

> Last updated: 2026-02-25
> Author: Claude Code (Opus 4.6)
> Purpose: Session continuity document — reboot/reconnect 후 이 파일을 참조하여 작업 이어서 진행

---

## 1. Project Overview

**Quant V3.1 Ubuntu Edition** — Regime-Adaptive Quantitative Trading System

| Item | Value |
|------|-------|
| OS | Ubuntu 24.04 LTS (VirtualBox VM) |
| DB | PostgreSQL 16 + TimescaleDB (Docker) |
| Engine | Python 3.11 (FastAPI + gRPC) |
| Dashboard | Blazor Server (.NET 8) |
| Cache | Redis 7 |
| Conda Env | `quant-v31` (`/home/quant/miniconda3/envs/quant-v31/`) |
| Project Root | `/home/quant/quant-v31` |

### Connection Info
```
PostgreSQL: postgresql://quant:QuantV31!Secure@localhost:5432/quantdb
Redis:      redis://localhost:6379
FastAPI:    http://localhost:8000
gRPC:       localhost:50051
Dashboard:  http://localhost:5000
```

---

## 2. Phase Completion Status

### PHASE 1: Infrastructure — COMPLETE
- Ubuntu 24.04 + Docker (PG+TimescaleDB+Redis) + Python 3.11 + .NET 8
- 1,506 symbols, 5,083,547 daily_prices rows (15-year OHLCV)
- Parquet data files in `data/parquet/`
- FinBERT model pre-downloaded for CPU inference

### PHASE 2: Regime Engine + Strategies — COMPLETE
- HMM 3-State Regime Detection (Bull/Sideways/Bear) — `engine/risk/regime.py`
- Kill Switch 3-Level (NORMAL→WARNING→DEFENSIVE→EMERGENCY) — `engine/risk/kill_switch.py`
- RegimeAllocator (strategy allocation matrix by regime) — `engine/risk/regime_allocator.py`
- DynamicPositionSizer (ATR-based, half-Kelly) — `engine/risk/position_sizer.py`
- 5 Strategies:
  1. `engine/strategies/lowvol_quality.py` — Low-Vol + Quality Factor
  2. `engine/strategies/vol_momentum.py` — Vol-Managed Momentum
  3. `engine/strategies/pairs_trading.py` — Cointegrated Pairs Mean-Reversion
  4. `engine/strategies/vol_targeting.py` — Volatility Targeting
  5. `engine/strategies/sentiment.py` — FinBERT + Claude Sentiment Hybrid

### PHASE 3: System Integration — COMPLETE
- **Step 3.1**: 8-step Daily Pipeline Orchestrator (`engine/api/main.py`)
  - Regime→KillSwitch→Allocation→Signals→Sentiment→VolTarget→Sizing→VWAP
- **Step 3.2**: Blazor Server Dashboard (6 pages: Portfolio, Regime, Risk, Strategies, Sentiment, Backtest)
  - Dark theme, SignalR real-time, Npgsql Raw SQL
- **Step 3.3**: gRPC Server + APScheduler (5 cron jobs) + SHAP Explainer + Telegram Alerts
- **Step 3.4**: 3 systemd services (engine, dashboard, scheduler) + E2E Test (39/39 pass)

### PHASE 4: Backtest Verification — COMPLETE
- **Step 4.1**: 7 new DB tables (backtest_runs, walk_forward_results, monte_carlo_results, regime_stress_results, dsr_results, granger_results, go_stop_log) + 5 hypertables + BacktestEngine core
- **Step 4.2**: Walk-Forward Validator (36m/6m), Deflated Sharpe Ratio (DSR), Monte Carlo Simulator (block bootstrap)
- **Step 4.3**: Regime Stress Tester (4 scenarios), Granger Causality Tester
- **Step 4.4**: 12 new Backtest API routes + Backtest.razor dashboard page + NavMenu update
- Test: 23/23 pass

### PHASE 5: Paper Trading — NOT YET STARTED
- Paper Trading $100K+, 9-12 months continuous operation
- GO/STOP Decision (Sharpe>1.1, MDD<-18%, DSR>95%, FPR<15%)
- **This is the next phase to implement**

---

## 3. Test Results Summary

| Test Suite | Result | Command |
|-----------|--------|---------|
| E2E (Phase 3) | 39/39 PASS | `PYTHONPATH=/home/quant/quant-v31 /home/quant/miniconda3/envs/quant-v31/bin/python scripts/test_e2e.py --quick --no-systemd` |
| Phase 4 | 23/23 PASS | `PYTHONPATH=/home/quant/quant-v31 /home/quant/miniconda3/envs/quant-v31/bin/python scripts/test_phase4.py` |

---

## 4. Running Services

| Service | Port | Status | systemd |
|---------|------|--------|---------|
| PostgreSQL (Docker) | 5432 | active | docker.service |
| Redis (Docker) | 6379 | active | docker.service |
| FastAPI Engine | 8000 | active | quant-engine.service (enabled) |
| gRPC Server | 50051 | active | (part of quant-engine) |
| Blazor Dashboard | 5000 | active | quant-dashboard.service (enabled) |
| Scheduler | - | inactive | quant-scheduler.service (enabled, optional) |

### Service Management
```bash
# Status check
sudo systemctl status quant-engine quant-dashboard quant-scheduler

# Start/stop/restart
sudo bash scripts/manage_services.sh start|stop|restart|status

# Logs
sudo journalctl -u quant-engine -f
sudo journalctl -u quant-dashboard -f
```

---

## 5. Database Schema

### Tables (18 total)
| Table | Type | Rows | Phase |
|-------|------|------|-------|
| symbols | regular | 1,506 | P1 |
| daily_prices | hypertable | 5,083,547 | P1 |
| fundamentals | regular | - | P1 |
| cointegrated_pairs | regular | - | P2 |
| factor_scores | hypertable | - | P2 |
| regime_history | hypertable | 3 | P2 |
| kill_switch_log | hypertable | - | P2 |
| portfolio_snapshots | hypertable | - | P2 |
| sentiment_scores | hypertable | - | P2 |
| trades | regular | - | P2 |
| strategy_performance | hypertable | - | P2 |
| signal_log | hypertable | - | P2 |
| backtest_runs | regular | 0 | P4 |
| walk_forward_results | hypertable | 0 | P4 |
| monte_carlo_results | hypertable | 0 | P4 |
| regime_stress_results | hypertable | 0 | P4 |
| dsr_results | hypertable | 0 | P4 |
| granger_results | hypertable | 0 | P4 |
| go_stop_log | regular | 0 | P4 |

### Continuous Aggregates
- `weekly_prices` — defined in migrate_phase4.sql but may need refresh

---

## 6. File Structure (Source Files Only)

```
quant-v31/
├── CLAUDE.md                              # Claude Code project instructions
├── project_status.md                      # THIS FILE
├── docker-compose.yml
│
├── engine/                                # Python Engine (FastAPI + gRPC)
│   ├── __init__.py
│   ├── requirements.txt
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py                    # Pydantic Settings (all config)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                        # FastAPI + 8-step Orchestrator + ALL routes
│   │   └── grpc_server.py                 # gRPC server (Regime/Portfolio/Signal)
│   ├── data/
│   │   ├── __init__.py
│   │   └── storage.py                     # PostgresStore + RedisCache
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── regime.py                      # HMM RegimeDetector
│   │   ├── regime_allocator.py            # Strategy allocation by regime
│   │   ├── kill_switch.py                 # 3-level DrawdownKillSwitch
│   │   └── position_sizer.py             # ATR + Kelly position sizing
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py                        # Strategy base class
│   │   ├── lowvol_quality.py
│   │   ├── vol_momentum.py
│   │   ├── pairs_trading.py
│   │   ├── vol_targeting.py
│   │   └── sentiment.py                   # FinBERT + Claude hybrid
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── alpaca_client.py               # Alpaca Paper/Live trading
│   │   ├── vwap.py                        # VWAP split execution
│   │   ├── alerts.py                      # Telegram alerts
│   │   ├── scheduler.py                   # APScheduler (5 cron jobs)
│   │   └── scheduler_standalone.py        # Standalone scheduler entry
│   ├── explain/
│   │   ├── __init__.py
│   │   └── feature_importance.py          # SHAP explainer
│   └── backtest/                          # Phase 4
│       ├── __init__.py
│       ├── engine.py                      # BacktestEngine + compute_metrics
│       ├── walk_forward.py                # 36m/6m Walk-Forward Validator
│       ├── dsr.py                         # Deflated Sharpe Ratio
│       ├── monte_carlo.py                 # Block Bootstrap Monte Carlo
│       ├── regime_stress.py               # 4 Regime Stress Scenarios
│       └── granger_test.py                # Granger Causality Test
│
├── dashboard/QuantDashboard/              # Blazor Server (.NET 8)
│   ├── Program.cs                         # App entry + DI (PostgresService, GrpcClient, RealtimeHub)
│   ├── QuantDashboard.csproj
│   ├── Models/DashboardModels.cs          # All record types
│   ├── Services/
│   │   ├── PostgresService.cs             # Npgsql Raw SQL queries
│   │   ├── GrpcClient.cs                  # gRPC client (Regime/Portfolio/Signal)
│   │   └── RealtimeHub.cs                 # SignalR hub
│   ├── Components/
│   │   ├── App.razor
│   │   ├── Routes.razor
│   │   ├── _Imports.razor
│   │   ├── Layout/
│   │   │   ├── MainLayout.razor + .css    # Dark theme layout
│   │   │   └── NavMenu.razor + .css       # 6 nav items
│   │   └── Pages/
│   │       ├── Home.razor                 # Portfolio overview
│   │       ├── Regime.razor               # HMM regime state
│   │       ├── Risk.razor                 # Kill Switch + MDD
│   │       ├── Strategies.razor           # Strategy signals/performance
│   │       ├── Sentiment.razor            # FinBERT heatmap
│   │       └── Backtest.razor             # Phase 4 verification dashboard
│   └── wwwroot/
│       ├── app.css                        # Dark theme CSS
│       └── bootstrap/bootstrap.min.css
│
├── proto/                                 # gRPC definitions
│   ├── regime.proto
│   ├── portfolio.proto
│   └── signals.proto
│
├── scripts/
│   ├── init_db.sql                        # Phase 1-3 DB schema
│   ├── migrate_phase4.sql                 # Phase 4 DB migration (7 tables)
│   ├── manage_services.sh                 # systemd service management
│   ├── test_e2e.py                        # E2E test (39 tests)
│   ├── test_phase4.py                     # Phase 4 test (23 tests)
│   ├── test_step31.py                     # Step 3.1 test
│   ├── test_step33.py                     # Step 3.3 test (8 tests)
│   ├── verify_env.py
│   ├── benchmark_finbert.py
│   └── phase1/                            # Data collection scripts
│       ├── 01_build_universe.py
│       ├── 02_collect_ohlcv.py
│       ├── 03_collect_benchmarks.py
│       ├── 04_hmm_prototype.py
│       └── run_phase1.py
│
├── systemd/
│   ├── quant-engine.service
│   ├── quant-dashboard.service
│   └── quant-scheduler.service
│
├── docs/
│   ├── DevPlan.jsx                        # Full architecture design (4-phase roadmap)
│   ├── Strategy.jsx                       # Strategy design (HMM, Kill Switch, allocation)
│   ├── Phase3Guide.jsx                    # Phase 3 implementation guide
│   └── Guide.jsx                          # General guide
│
└── data/parquet/                          # 15-year OHLCV data (1,400+ symbols)
```

---

## 7. Key Configuration (engine/config/settings.py)

```python
# PostgreSQL
pg_dsn = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"

# Redis
redis_url = "redis://localhost:6379"

# Alpaca (Paper Trading)
alpaca_paper = True
alpaca_base_url = "https://paper-api.alpaca.markets"

# HMM Regime
hmm_n_states = 3
hmm_lookback_days = 504    # 2 years
hmm_retrain_interval = 30  # monthly

# Risk
risk_per_trade = 0.02      # 2%
kelly_fraction = 0.5       # half-Kelly
max_position_pct = 0.10    # 10% max per position
max_sector_pct = 0.25      # 25% max per sector

# gRPC
grpc_port = 50051

# Scheduler
scheduler_timezone = "US/Eastern"
pipeline_hour = 15, pipeline_minute = 30  # 3:30 PM ET

# Backtest (Phase 4)
backtest_years = 15
walk_forward_train = 36    # 36-month train window
walk_forward_test = 6      # 6-month test window
slippage_bps = 5.0
monte_carlo_sims = 10000
dsr_threshold = 0.95
go_sharpe_min = 1.1
go_mdd_max = -0.18
go_paper_months = 9
```

---

## 8. API Routes Summary

### Phase 3 Routes (engine/api/main.py)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/run` | Trigger daily pipeline (background) |
| GET | `/regime` | Current regime state |
| GET | `/kill-switch` | Kill Switch status |
| GET | `/portfolio` | Latest portfolio snapshot |
| GET | `/account` | Alpaca account info |
| GET | `/scheduler` | APScheduler job status |
| GET | `/explain/regime` | SHAP regime feature importance |
| GET | `/explain/strategy/{strategy}` | Strategy signal stats |
| GET | `/signals` | Recent signals |

### Phase 4 Routes (Backtest)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/backtest/runs` | Backtest run history |
| GET | `/backtest/runs/{run_id}` | Single run detail |
| POST | `/backtest/walk-forward` | Trigger Walk-Forward (background) |
| POST | `/backtest/monte-carlo` | Trigger Monte Carlo (background) |
| POST | `/backtest/stress-test` | Trigger Regime Stress Test (background) |
| POST | `/backtest/dsr` | Trigger DSR calculation (background) |
| POST | `/backtest/granger` | Trigger Granger test (background) |
| GET | `/backtest/walk-forward/results` | Walk-Forward results |
| GET | `/backtest/monte-carlo/results` | Monte Carlo results |
| GET | `/backtest/stress-test/results` | Stress test results |
| GET | `/backtest/dsr/results` | DSR results |
| GET | `/backtest/granger/results` | Granger results |
| GET | `/backtest/go-stop` | GO/STOP decision |

---

## 9. Blazor Dashboard Pages

| Page | Route | Description |
|------|-------|-------------|
| Home.razor | `/` | Portfolio overview (equity curve, daily P&L, metrics) |
| Regime.razor | `/regime` | HMM regime gauge, transition history |
| Risk.razor | `/risk` | Kill Switch status, MDD tracking, exposure |
| Strategies.razor | `/strategies` | Strategy signals, performance table |
| Sentiment.razor | `/sentiment` | FinBERT sentiment heatmap |
| Backtest.razor | `/backtest` | Phase 4 verification (WF, DSR, MC, Stress, GO/STOP) |

---

## 10. Known Issues & Notes

### VirtualBox Limitations
- **Polars AVX crash**: Base conda Python 3.13 has Polars requiring AVX/AVX2. Must use `quant-v31` conda env (Python 3.11) instead of base
- **Single-worker uvicorn**: Pairs trading cointegration blocks on slow VM. Pipeline POST `/run` may timeout — this is expected
- Always use: `/home/quant/miniconda3/envs/quant-v31/bin/python`
- Always set: `PYTHONPATH=/home/quant/quant-v31`

### DB Column Names
- `signal_log` uses `time` column (NOT `generated_at`)
- All hypertables use `time` as the time column

### Docker
- Docker requires sudo or membership in docker group
- Port-based checking preferred over `docker inspect` (avoids sudo)

### Continuous Aggregates
- `weekly_prices` was defined in migrate_phase4.sql
- `portfolio_daily` referenced in main.py refresh — may need to be created separately

---

## 11. Phase 4 Backtest Modules Detail

### BacktestEngine (`engine/backtest/engine.py`)
- `compute_metrics(daily_returns)` → BacktestMetrics (Sharpe, CAGR, MDD, Calmar, Sortino, etc.)
- `BacktestEngine.run(start, end)` → BacktestResult with equity curve, regimes, kill levels
- Uses SPY as portfolio proxy, regime-adaptive allocation, slippage model
- `BacktestStore` — create_run/complete_run/fail_run for DB tracking

### Walk-Forward (`engine/backtest/walk_forward.py`)
- 36-month train / 6-month test rolling window
- Degradation ratio: OOS Sharpe / IS Sharpe
- Pass condition: avg OOS Sharpe >= 1.1 (go_sharpe_min)

### DSR (`engine/backtest/dsr.py`)
- Bailey & Lopez de Prado (2014) — selection bias correction
- Non-normality adjustment (skewness + kurtosis)
- n_trials parameter for multiple strategy testing
- Pass condition: DSR > 95%

### Monte Carlo (`engine/backtest/monte_carlo.py`)
- Block bootstrap (21-day blocks preserve autocorrelation)
- 10,000 simulations default
- Reports: CAGR/Sharpe/MDD distributions (p5/p50/p95), P(negative), P(MDD>20%)

### Regime Stress (`engine/backtest/regime_stress.py`)
- 4 scenarios:
  - `covid_crash`: 2020-01-15 ~ 2020-04-30 (Bull→Bear)
  - `rate_hike`: 2022-01-03 ~ 2022-10-31 (Bull→Bear)
  - `recovery`: 2020-03-23 ~ 2021-01-31 (Bear→Bull)
  - `vix_spike`: 2018-01-26 ~ 2018-04-30 (VIX 15→50)
- Measures: regime accuracy, FPR, detection lag, kill switch, recovery days
- Pass: accuracy>=50%, FPR<25%, MDD>-30%

### Granger Causality (`engine/backtest/granger_test.py`)
- statsmodels grangercausalitytests
- Tests sentiment→price and price→sentiment bidirectionally
- Pass: 30%+ symbols significant at p<0.05

---

## 12. Design Documents Reference

| Document | Path | Content |
|----------|------|---------|
| DevPlan.jsx | `docs/DevPlan.jsx` | Full 4-Phase roadmap, DB schema, code examples (1,818 lines) |
| Strategy.jsx | `docs/Strategy.jsx` | HMM, Kill Switch, 5 strategies, allocation matrix |
| Phase3Guide.jsx | `docs/Phase3Guide.jsx` | Phase 3 detailed implementation guide |
| Guide.jsx | `docs/Guide.jsx` | General project guide |

### GO/STOP Decision Criteria (from DevPlan.jsx)
| Criteria | GO Threshold | STOP Threshold |
|----------|-------------|----------------|
| Paper Sharpe | > 1.1 | < 0.8 (3 consecutive months) |
| MDD | > -18% | < -20% |
| DSR | > 95% | - |
| HMM FPR | < 15% | - |
| Paper Duration | >= 9 months | - |

---

## 13. What To Do Next — PHASE 5 Planning

The project roadmap (DevPlan.jsx) defines 4 phases. Phase 4 code is complete. The remaining work:

### Immediate Next Steps
1. **Run actual backtests** using the Phase 4 modules:
   - Trigger Walk-Forward: `POST http://localhost:8000/backtest/walk-forward`
   - Trigger Monte Carlo: `POST http://localhost:8000/backtest/monte-carlo`
   - Trigger Stress Test: `POST http://localhost:8000/backtest/stress-test`
   - Trigger DSR: `POST http://localhost:8000/backtest/dsr`
   - Trigger Granger: `POST http://localhost:8000/backtest/granger`
   - Note: These need SPY data in daily_prices (5M+ rows already exist)

2. **Implement GO/STOP auto-decision logic**:
   - Write code that aggregates all backtest results
   - Compare against GO thresholds
   - Insert decision into `go_stop_log` table

3. **Paper Trading Phase** (9-12 months):
   - Configure Alpaca Paper API keys in `.env`
   - Start daily pipeline via scheduler
   - Monitor via Blazor Dashboard at http://localhost:5000

### Possible Phase 5 Extensions (Not in docs, future consideration)
- Live trading transition ($5K-10K)
- Additional strategies
- Performance monitoring dashboard enhancements
- Alerting system improvements

---

## 14. Quick Command Reference

```bash
# Activate conda environment
conda activate quant-v31

# Run Python with correct PYTHONPATH
PYTHONPATH=/home/quant/quant-v31 /home/quant/miniconda3/envs/quant-v31/bin/python <script>

# Run tests
PYTHONPATH=/home/quant/quant-v31 python scripts/test_e2e.py --quick --no-systemd
PYTHONPATH=/home/quant/quant-v31 python scripts/test_phase4.py

# Service management
sudo bash scripts/manage_services.sh status
sudo bash scripts/manage_services.sh restart

# Build dashboard
cd dashboard/QuantDashboard && dotnet build --no-restore

# Check API
curl http://localhost:8000/health
curl http://localhost:8000/regime
curl http://localhost:8000/backtest/runs

# Database
psql postgresql://quant:QuantV31!Secure@localhost:5432/quantdb

# Docker
sudo docker ps
sudo docker-compose -f docker-compose.yml up -d
```

---

## 15. For Claude Code — Session Continuity Instructions

When a new Claude Code session starts after reboot:

1. **Read this file first**: `project_status.md`
2. **Read CLAUDE.md**: Project-level instructions and coding conventions
3. **Current state**: Phase 1~4 COMPLETE, all tests passing (39/39 E2E + 23/23 Phase 4)
4. **Services running**: engine(8000), gRPC(50051), dashboard(5000), PG(5432), Redis(6379)
5. **Git status**: All changes are untracked (single initial commit `583500a`)
6. **Next action**: Ask user what they want to do next (run backtests, implement GO/STOP, start Phase 5, etc.)

### Important Reminders
- Always use `quant-v31` conda env (NOT base — Polars AVX crash on VM)
- Always set `PYTHONPATH=/home/quant/quant-v31` for Python scripts
- Use `psycopg` (psycopg3), NOT psycopg2
- Blazor uses Npgsql Raw SQL, NOT Entity Framework
- All time-series tables are TimescaleDB hypertables
- `signal_log.time` column (not `generated_at`)
