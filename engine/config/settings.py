"""
V3.1 Phase 3 — Pydantic 설정 관리
.env 파일 또는 환경변수에서 자동 로드
"""
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from pathlib import Path


class Settings(BaseSettings):
    """V3.1 전역 설정"""

    # ─── PostgreSQL ───
    pg_dsn: str = Field(
        default="postgresql://quant:QuantV31!Secure@localhost:5432/quantdb",
        alias="PG_DSN",
    )

    @model_validator(mode="after")
    def _clean_pg_dsn(self):
        """postgresql+psycopg:// → postgresql:// 변환 (psycopg3 호환)"""
        self.pg_dsn = self.pg_dsn.replace("postgresql+psycopg://", "postgresql://")
        return self

    # ─── Redis ───
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    # ─── Alpaca ───
    alpaca_key: str = Field(default="", alias="ALPACA_KEY")
    alpaca_secret: str = Field(default="", alias="ALPACA_SECRET")
    alpaca_paper: bool = True
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    # ─── Telegram ───
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # ─── Claude API ───
    anthropic_key: str = Field(default="", alias="ANTHROPIC_KEY")

    # ─── HMM 레짐 ───
    hmm_n_states: int = 3
    hmm_lookback_days: int = 504  # 2년
    hmm_retrain_interval: int = 30  # 월간 재학습

    # ─── 리스크 ───
    risk_per_trade: float = 0.02
    kelly_fraction: float = 0.5
    max_position_pct: float = 0.10
    max_sector_pct: float = 0.25

    # ─── 실행 ───
    vwap_slices: int = 5
    vwap_interval_sec: int = 60

    # ─── FinBERT ───
    finbert_model: str = "ProsusAI/finbert"
    finbert_threshold: float = 0.7
    claude_enabled: bool = False

    # ─── gRPC ───
    grpc_port: int = 50051
    grpc_max_workers: int = 10

    # ─── Scheduler (미국 동부시간) ───
    scheduler_enabled: bool = True
    scheduler_timezone: str = "US/Eastern"
    pipeline_hour: int = 15
    pipeline_minute: int = 30

    # ─── Backtest (Phase 4) ───
    backtest_years: int = 15
    walk_forward_train: int = 36       # 36개월 학습 윈도우
    walk_forward_test: int = 6         # 6개월 테스트 윈도우
    slippage_bps: float = 5.0          # 5 bps 슬리피지
    monte_carlo_sims: int = 10000      # MC 시뮬레이션 횟수
    dsr_threshold: float = 0.95        # DSR 통과 기준
    go_sharpe_min: float = 1.1         # GO 최소 Sharpe
    go_mdd_max: float = -0.18          # GO 최대 MDD
    go_paper_months: int = 9           # GO 최소 Paper Trading 기간

    # ─── 경로 ───
    model_dir: Path = Path("/home/quant/quant-v31/models")
    data_dir: Path = Path("/home/quant/quant-v31/data")

    model_config = {
        "env_file": "/home/quant/quant-v31/.env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
