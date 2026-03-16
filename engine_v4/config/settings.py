"""Swing Trading Engine — Configuration (Pydantic v2 Settings)."""

from __future__ import annotations

from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class SwingSettings(BaseSettings):
    """All configuration loaded from .env + environment variables."""

    # ── Database ──
    pg_dsn: str = Field(
        default="postgresql://quant:QuantV31!Secure@localhost:5432/quantdb",
        alias="PG_DSN",
    )
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    # ── KIS 한국투자증권 ──
    kis_app_key: str = Field(default="", alias="KIS_APP_KEY")
    kis_app_secret: str = Field(default="", alias="KIS_APP_SECRET")
    kis_account_no: str = Field(default="", alias="KIS_ACCOUNT_NO")
    kis_is_paper: bool = Field(default=True, alias="KIS_IS_PAPER")

    # ── Anthropic (Claude API) ──
    anthropic_key: str = Field(default="", alias="ANTHROPIC_KEY")

    # ── Ollama (Local LLM) ──
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="qwen2.5:3b", alias="OLLAMA_MODEL")

    # ── Reddit (Social Sentiment) ──
    reddit_client_id: str = Field(default="", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", alias="REDDIT_CLIENT_SECRET")

    # ── Finnhub ──
    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")

    # ── Multi-Factor Scoring ──
    factor_scoring_enabled: bool = True

    # ── Telegram ──
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # ── Strategy Parameters ──
    sma_short: int = 50
    sma_long: int = 200
    return_period: int = 20
    return_rank_min: float = 0.6        # top 40% → percentile ≥ 0.6
    breakout_days: int = 5
    volume_ratio_min: float = 1.5

    # ── Risk Parameters ──
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.10
    max_positions: int = 4
    position_pct: float = 0.05          # 5% of account per position
    max_daily_entries: int = 1

    # ── Execution ──
    trading_mode: str = "paper"          # paper / live
    price_range_min: float = 20.0
    price_range_max: float = 80.0
    signal_expiry_hours: int = 24

    # ── Engine ──
    api_host: str = "0.0.0.0"
    api_port: int = 8001                 # V3.1은 8000, V4는 8001
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _clean_pg_dsn(self):
        self.pg_dsn = self.pg_dsn.replace("postgresql+psycopg://", "postgresql://")
        return self

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# ── Singleton ──
_settings: SwingSettings | None = None


def get_config() -> SwingSettings:
    global _settings
    if _settings is None:
        _settings = SwingSettings()
    return _settings
