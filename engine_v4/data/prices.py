"""yfinance 시세 조회 — 스레드 안전 + 심볼 검증 (2026-11-18 스냅샷 오염 수정).

사고: 2026-11-17 20:22:02 UTC 스냅샷에서 UPRO(≈$126)가 $433 으로 평가돼 총자산 $1,649 → $5,695 로 튀었고,
그 뒤 스냅샷의 max_drawdown 이 −201% 가 됐다. 41초 전 스냅샷은 정상, 그 시각 대시보드가 /watchlist/*
(MSFT ≈$430 등)를 동시에 조회 중이었다. `yf.download` 는 결과를 모듈 전역(yfinance.shared._DFS 등)에
모으므로 스레드 두 개가 동시에 부르면 서로의 종목이 섞인다. 단일 심볼 분기 `data["Close"].dropna().iloc[-1]`
는 열 이름을 보지 않아 섞여 들어온 다른 종목의 가격을 그대로 받았다.

대책:
1) install_download_lock(): 프로세스 전역 `yf.download` 를 잠금으로 직렬화 — 모든 호출부(약 30곳)가
   `yf.download` 를 호출 시점에 속성으로 찾으므로 엔진 시작 시 1회 설치하면 전부 덮인다.
2) last_closes(): 열을 **심볼 이름으로** 고르고(없으면 결손), 기준가(마지막 관측가) 대비 max_jump 를 넘으면
   Ticker.history 로 재조회해 두 출처가 일치할 때만 받는다. 불일치면 결손 → 호출부의 기존 폴백(마지막 관측가).
"""
from __future__ import annotations

import logging
import math
import threading

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_installed = False


def install_download_lock() -> None:
    """yf.download 를 전역 잠금 래퍼로 교체(멱등)."""
    global _installed
    if _installed:
        return
    raw = yf.download

    def locked_download(*args, **kwargs):
        with _LOCK:
            return raw(*args, **kwargs)

    locked_download.__wrapped__ = raw
    yf.download = locked_download
    _installed = True
    logger.info("yfinance download lock installed (스레드 간 결과 섞임 방지)")


def _finite(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _close_col(data: pd.DataFrame, sym: str, n_syms: int) -> pd.Series | None:
    """download 결과에서 sym 의 Close 열만. 열 이름으로 확인할 수 없으면 None(다른 종목일 수 있다)."""
    if data is None or data.empty:
        return None
    if isinstance(data.columns, pd.MultiIndex):
        lv0 = data.columns.get_level_values(0)
        if "Close" in lv0:                       # (필드, 티커) — yfinance 기본
            close = data["Close"]
            return close[sym] if sym in close.columns else None
        if sym in lv0:                           # group_by="ticker" — (티커, 필드)
            sub = data[sym]
            return sub["Close"] if "Close" in sub.columns else None
        return None
    # 단일 수준 열 = 심볼 이름이 없다 → 단일 심볼 요청일 때만 받는다
    return data["Close"] if n_syms == 1 and "Close" in data.columns else None


def last_closes(symbols: list[str], ref: dict[str, float] | None = None, period: str = "2d",
                max_jump: float = 0.5) -> tuple[dict[str, float], list[str]]:
    """심볼별 최신 종가(장중이면 최신 봉). 반환 (prices, rejected).
    ref[sym] 대비 |변화| > max_jump 이면 Ticker.history 로 재확인 — 두 값이 2% 안이면 진짜 움직임으로 받고, 아니면 버린다."""
    syms = sorted(set(symbols))
    out: dict[str, float] = {}
    rejected: list[str] = []
    if not syms:
        return out, rejected
    install_download_lock()
    try:
        data = yf.download(syms, period=period, progress=False, auto_adjust=True)
    except Exception as e:
        logger.warning(f"yfinance download failed: {e}")
        return out, syms
    for s in syms:
        col = _close_col(data, s, len(syms))
        px = _finite(col.dropna().iloc[-1]) if col is not None and not col.dropna().empty else None
        if px is None:
            rejected.append(s)
            continue
        r = _finite((ref or {}).get(s))
        if r is not None and abs(px / r - 1) > max_jump:
            try:
                with _LOCK:
                    h = yf.Ticker(s).history(period="5d", auto_adjust=True)
                px2 = _finite(h["Close"].dropna().iloc[-1]) if not h.empty else None
            except Exception:
                px2 = None
            if px2 is None or abs(px2 / px - 1) > 0.02:
                logger.error(f"🔴 시세 검증 실패 {s}: download ${px:.2f} vs history "
                             f"{'—' if px2 is None else f'${px2:.2f}'} (기준 ${r:.2f}) — 버림")
                rejected.append(s)
                continue
            logger.warning(f"{s} 급변 확인됨: ${r:.2f} → ${px:.2f} (두 출처 일치)")
        out[s] = px
    return out, rejected
