"""MacroScorer — 5개 매크로 서브시그널 → 종합 점수 (0-100).

Sub-signals:
  1. Risk-Off Regime (VIX + Gold/SPY + HY spread): 30%
  2. Yield Curve (10Y 금리 수준 + 방향): 20%
  3. Copper/Gold Ratio (경기 선행): 20%
  4. Dollar Trend (DXY 모멘텀): 15%
  5. BTC Momentum (위험 선호 프록시): 15%

Score 해석:
  80-100: 매우 유리한 매크로 (risk-on, 성장)
  60-80:  유리 (정상 환경)
  40-60:  중립/혼합
  20-40:  불리 (주의)
  0-20:   매우 불리 (risk-off, 방어적)
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MacroScorer:
    """매크로 오버레이 스코어러 — 5개 서브시그널 가중 합산."""

    SUB_WEIGHTS = {
        "risk_off": 0.30,
        "yield_curve": 0.20,
        "copper_gold": 0.20,
        "dollar_trend": 0.15,
        "btc_momentum": 0.15,
    }

    CACHE_KEY = "macro_score"
    CACHE_TTL = 14400  # 4시간

    def __init__(self, macro_collector, cache=None):
        self.collector = macro_collector
        self.cache = cache

    def calc_macro_score(self, force_collect: bool = False) -> dict:
        """매크로 종합 점수 계산.

        Returns:
            {macro_score, risk_off, yield_curve, copper_gold, dollar_trend,
             btc_momentum, regime, weights, raw_data, scored_at}
        """
        # 캐시 확인
        if not force_collect and self.cache:
            cached = self.cache.get_json(self.CACHE_KEY)
            if cached:
                logger.debug("Macro score from cache")
                return cached

        # 매크로 데이터 수집
        data = self.collector.collect_macro_data(force=force_collect)
        if data.get("status") != "ok":
            logger.warning(f"Macro data unavailable: {data.get('status')}")
            return self._neutral_result(data)

        # 5개 서브시그널 계산
        risk_off = self._score_risk_off(data)
        yield_curve = self._score_yield_curve(data)
        copper_gold = self._score_copper_gold(data)
        dollar_trend = self._score_dollar_trend(data)
        btc_momentum = self._score_btc_momentum(data)

        # 가중 합산
        macro_score = (
            risk_off["score"] * self.SUB_WEIGHTS["risk_off"] +
            yield_curve["score"] * self.SUB_WEIGHTS["yield_curve"] +
            copper_gold["score"] * self.SUB_WEIGHTS["copper_gold"] +
            dollar_trend["score"] * self.SUB_WEIGHTS["dollar_trend"] +
            btc_momentum["score"] * self.SUB_WEIGHTS["btc_momentum"]
        )
        macro_score = round(max(0, min(100, macro_score)), 1)

        regime = self._determine_regime(macro_score)

        result = {
            "macro_score": macro_score,
            "risk_off": risk_off,
            "yield_curve": yield_curve,
            "copper_gold": copper_gold,
            "dollar_trend": dollar_trend,
            "btc_momentum": btc_momentum,
            "regime": regime,
            "weights": dict(self.SUB_WEIGHTS),
            "raw_data": {
                "vix": data.get("vix"),
                "yield_10y": data.get("yield_10y"),
                "dxy": data.get("dxy"),
                "gold_spy_ratio": data.get("gold_spy_ratio"),
                "hy_spread": data.get("hy_spread"),
                "copper_gold_ratio": data.get("copper_gold_ratio"),
                "btc_momentum_20d": data.get("btc_momentum_20d"),
                "dxy_momentum_20d": data.get("dxy_momentum_20d"),
            },
            "scored_at": datetime.now().isoformat(),
        }

        # Redis 캐시
        if self.cache:
            self.cache.set_json(self.CACHE_KEY, result, ttl=self.CACHE_TTL)

        logger.info(f"Macro score: {macro_score:.1f} [{regime}] — "
                     f"RiskOff={risk_off['score']:.0f} Yield={yield_curve['score']:.0f} "
                     f"CuAu={copper_gold['score']:.0f} DXY={dollar_trend['score']:.0f} "
                     f"BTC={btc_momentum['score']:.0f}")

        return result

    # ──────────────────────────────────────────────────────
    # Sub-signal scorers (각각 0-100 반환)
    # ──────────────────────────────────────────────────────

    def _score_risk_off(self, data: dict) -> dict:
        """VIX + Gold/SPY + HY Spread 복합 Risk-Off 스코어.

        VIX (40%): 낮을수록 Risk-On → 높은 점수
        Gold/SPY (30%): 하락 추세 = Risk-On → 높은 점수
        HY Spread (30%): 좁을수록 Risk-On → 높은 점수
        """
        # --- VIX scoring (40%) ---
        vix = data.get("vix")
        vix_sma = data.get("vix_sma_20")
        if vix is not None:
            if vix < 15:
                vix_score = 90
            elif vix < 18:
                vix_score = 75
            elif vix < 22:
                vix_score = 55
            elif vix < 28:
                vix_score = 35
            elif vix < 35:
                vix_score = 20
            else:
                vix_score = 5

            # VIX가 SMA20 대비 10% 이상 높으면 추가 감점
            if vix_sma and vix > vix_sma * 1.1:
                vix_score = max(0, vix_score - 10)
        else:
            vix_score = 50  # 데이터 없으면 중립

        # --- Gold/SPY ratio scoring (30%) ---
        ratio = data.get("gold_spy_ratio")
        ratio_20d = data.get("gold_spy_ratio_20d")
        if ratio is not None and ratio_20d is not None and ratio_20d > 0:
            ratio_change = (ratio / ratio_20d - 1) * 100
            # 비율 하락 = 주식 강세 = Risk-On = 높은 점수
            if ratio_change < -3:
                gs_score = 85  # 금 약세 / 주식 강세
            elif ratio_change < -1:
                gs_score = 70
            elif ratio_change < 1:
                gs_score = 50  # 중립
            elif ratio_change < 3:
                gs_score = 35
            else:
                gs_score = 15  # 금 급등 / 주식 약세
        else:
            gs_score = 50

        # --- HY Spread scoring (30%) ---
        # LQD/HYG 비율: 높을수록 스프레드 확대 = Risk-Off
        hy = data.get("hy_spread")
        if hy is not None:
            # 일반적인 LQD/HYG 비율 범위: ~1.30-1.55
            if hy < 1.35:
                hy_score = 85  # 타이트 스프레드 = Risk-On
            elif hy < 1.40:
                hy_score = 70
            elif hy < 1.45:
                hy_score = 50
            elif hy < 1.50:
                hy_score = 30
            else:
                hy_score = 10  # 와이드 스프레드 = Risk-Off
        else:
            hy_score = 50

        score = vix_score * 0.4 + gs_score * 0.3 + hy_score * 0.3

        return {
            "score": round(score, 1),
            "detail": f"VIX={vix_score} Gold/SPY={gs_score} HY={hy_score}",
            "vix_score": vix_score,
            "gold_spy_score": gs_score,
            "hy_score": hy_score,
        }

    def _score_yield_curve(self, data: dict) -> dict:
        """10Y 국채 금리 수준 + 방향 기반 스코어.

        적정 금리(2-4%) = 성장 환경 → 높은 점수
        금리 급등(>5%) = 긴축 부담 → 낮은 점수
        금리 급락(<2%) = 경기침체 우려 → 낮은 점수
        """
        yield_10y = data.get("yield_10y")  # %단위
        if yield_10y is None:
            return {"score": 50, "detail": "no data"}

        # 수준 기반 점수
        if 2.5 <= yield_10y <= 4.0:
            level_score = 80  # 골디락스 구간
        elif 2.0 <= yield_10y <= 4.5:
            level_score = 65
        elif 1.5 <= yield_10y <= 5.0:
            level_score = 45
        elif yield_10y > 5.0:
            level_score = 25  # 긴축 과도
        else:
            level_score = 30  # <1.5% 경기침체 우려

        # 방향 보정: TNX 20일 변화
        tnx = data.get("tnx")
        tnx_20d = data.get("tnx_20d_ago")
        direction_adj = 0
        if tnx is not None and tnx_20d is not None and tnx_20d > 0:
            change = tnx - tnx_20d  # TNX 포인트 변화 (×10 스케일)
            if change > 5:  # 50bp+ 급등
                direction_adj = -15  # 금리 급등 = 주식 부담
            elif change > 2:
                direction_adj = -5
            elif change < -5:  # 50bp+ 급락
                direction_adj = -10  # 급락도 경기 우려
            elif change < -2:
                direction_adj = 5  # 완만한 하락은 주식 유리

        score = max(0, min(100, level_score + direction_adj))

        return {
            "score": round(score, 1),
            "detail": f"10Y={yield_10y:.2f}% level={level_score} dir_adj={direction_adj}",
            "yield_10y": yield_10y,
        }

    def _score_copper_gold(self, data: dict) -> dict:
        """구리/금 비율 — 경기 확장/수축 바로미터.

        비율 상승 = 산업 수요 강세 = 경기 확장 → 높은 점수
        비율 하락 = 안전자산 선호 = 경기 수축 → 낮은 점수
        """
        ratio = data.get("copper_gold_ratio")
        if ratio is None:
            return {"score": 50, "detail": "no data"}

        # 구리/금 비율: HG=F (~$4.5/lb) / GC=F (~$3000/oz) ≈ 0.0015
        # 실제 범위: 0.0010 ~ 0.0020
        if ratio > 0.0016:
            level_score = 85  # 강한 경기 확장
        elif ratio > 0.0014:
            level_score = 70
        elif ratio > 0.0012:
            level_score = 50
        elif ratio > 0.0010:
            level_score = 30
        else:
            level_score = 15  # 경기 수축

        # 방향 보정 (구리/금 20일 전 대비)
        copper_20d = data.get("copper_20d_ago")
        gold_20d = data.get("gold_20d_ago")
        direction_adj = 0
        if copper_20d and gold_20d and gold_20d > 0:
            ratio_20d = copper_20d / gold_20d
            if ratio_20d > 0:
                change_pct = (ratio / ratio_20d - 1) * 100
                if change_pct > 3:
                    direction_adj = 10  # 비율 상승 추세
                elif change_pct > 1:
                    direction_adj = 5
                elif change_pct < -3:
                    direction_adj = -10  # 비율 하락 추세
                elif change_pct < -1:
                    direction_adj = -5

        score = max(0, min(100, level_score + direction_adj))

        return {
            "score": round(score, 1),
            "detail": f"Cu/Au={ratio:.6f} level={level_score} dir={direction_adj}",
            "ratio": ratio,
        }

    def _score_dollar_trend(self, data: dict) -> dict:
        """달러 강약 (DXY 20일 모멘텀).

        달러 약세 = 유동성 확대 = 주식 유리 → 높은 점수
        달러 강세 = 유동성 축소 = 주식 불리 → 낮은 점수
        """
        dxy_mom = data.get("dxy_momentum_20d")  # %
        if dxy_mom is None:
            return {"score": 50, "detail": "no data"}

        # DXY 20일 수익률 기반 점수 (역방향)
        if dxy_mom < -3:
            score = 85   # 달러 급락 = 주식 매우 유리
        elif dxy_mom < -1.5:
            score = 72
        elif dxy_mom < -0.5:
            score = 60
        elif dxy_mom < 0.5:
            score = 50   # 중립
        elif dxy_mom < 1.5:
            score = 38
        elif dxy_mom < 3:
            score = 25
        else:
            score = 12   # 달러 급등 = 주식 매우 불리

        return {
            "score": round(score, 1),
            "detail": f"DXY 20d={dxy_mom:+.1f}%",
            "dxy_momentum": dxy_mom,
        }

    def _score_btc_momentum(self, data: dict) -> dict:
        """BTC 20일 모멘텀 — 위험선호 프록시.

        BTC 강세 = 위험 선호(Risk-On) → 높은 점수
        BTC 약세 = 위험 회피(Risk-Off) → 낮은 점수
        """
        btc_mom = data.get("btc_momentum_20d")  # %
        if btc_mom is None:
            return {"score": 50, "detail": "no data"}

        if btc_mom > 20:
            score = 90   # 극도 Risk-On
        elif btc_mom > 10:
            score = 78
        elif btc_mom > 3:
            score = 65
        elif btc_mom > -3:
            score = 50   # 중립
        elif btc_mom > -10:
            score = 35
        elif btc_mom > -20:
            score = 22
        else:
            score = 10   # 극도 Risk-Off

        return {
            "score": round(score, 1),
            "detail": f"BTC 20d={btc_mom:+.1f}%",
            "btc_momentum": btc_mom,
        }

    # ──────────────────────────────────────────────────────

    @staticmethod
    def _determine_regime(macro_score: float) -> str:
        """매크로 레짐 분류."""
        if macro_score >= 65:
            return "RISK_ON"
        elif macro_score >= 45:
            return "NEUTRAL"
        elif macro_score >= 25:
            return "RISK_OFF"
        else:
            return "CRISIS"

    @staticmethod
    def _neutral_result(data: dict) -> dict:
        """데이터 미수집 시 중립 결과."""
        neutral = {"score": 50.0, "detail": "no data"}
        return {
            "macro_score": 50.0,
            "risk_off": neutral,
            "yield_curve": neutral,
            "copper_gold": neutral,
            "dollar_trend": neutral,
            "btc_momentum": neutral,
            "regime": "NEUTRAL",
            "weights": MacroScorer.SUB_WEIGHTS,
            "raw_data": {},
            "scored_at": datetime.now().isoformat(),
        }
