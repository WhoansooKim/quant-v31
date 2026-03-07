"""StrategyOptimizer — LLM 기반 전략 파라미터 최적화.

1. 현재 파라미터 + 백테스트 결과 → Claude에 전달
2. Claude가 5개 파라미터 세트 제안
3. 각 세트로 백테스트 자동 실행
4. 결과 비교 → 최고 Sharpe/최저 MDD 선택
5. 최종 리포트 반환 (사람이 승인 시 적용)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import date

from engine_v4.backtest.runner import BacktestParams, BacktestRunner
from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

OPTIMIZE_PROMPT = """You are a quantitative strategist optimizing a momentum swing trading strategy.

Current Parameters:
{current_params}

Current Backtest Results ({period}):
- Total Return: {total_return}
- CAGR: {cagr}
- Max Drawdown: {max_drawdown}
- Sharpe Ratio: {sharpe}
- Win Rate: {win_rate}
- Total Trades: {total_trades}
- Profit Factor: {profit_factor}

Suggest exactly 5 different parameter sets that might improve the Sharpe Ratio and reduce Max Drawdown.
Each set should vary meaningfully from the current parameters.

Parameter constraints:
- sma_short: 20-100 (must be < sma_long)
- sma_long: 100-300
- return_rank_min: 0.4-0.9 (higher = more selective)
- volume_ratio_min: 1.0-3.0
- stop_loss_pct: -0.03 to -0.10 (negative)
- take_profit_pct: 0.05 to 0.25
- max_positions: 2-8
- position_pct: 0.03-0.15
- price_range_min: 10-50
- price_range_max: 100-500

Respond with a JSON array of 5 objects. Each object has a "label" (short description) and the parameter values.
Example:
[
  {{"label": "Tight stops, wider universe", "stop_loss_pct": -0.03, "take_profit_pct": 0.08, "return_rank_min": 0.5, ...}},
  ...
]

Respond ONLY with the JSON array, no other text."""


class StrategyOptimizer:
    """LLM 기반 전략 최적화 에이전트."""

    def __init__(self, pg: PostgresStore, backtester: BacktestRunner,
                 anthropic_key: str = ""):
        self.pg = pg
        self.backtester = backtester
        self._claude = None

        if anthropic_key and anthropic_key not in ("", "your_anthropic_key_here"):
            try:
                import anthropic
                self._claude = anthropic.Anthropic(api_key=anthropic_key)
                logger.info("StrategyOptimizer: Claude API ready")
            except (ImportError, Exception) as e:
                logger.warning(f"StrategyOptimizer: Claude unavailable: {e}")

    @property
    def is_available(self) -> bool:
        return self._claude is not None

    def optimize(self, rounds: int = 1,
                 start_date: date = date(2022, 1, 1),
                 end_date: date = date(2025, 12, 31),
                 initial_capital: float = 10000.0) -> dict:
        """최적화 실행.

        1. 현재 파라미터로 baseline 백테스트
        2. Claude에게 5개 변형 요청
        3. 각 변형으로 백테스트
        4. 결과 비교 + 리포트 반환
        """
        total_start = time.time()

        # Baseline params from DB config
        base_params = self._load_current_params(start_date, end_date, initial_capital)

        # Step 1: Baseline backtest
        logger.info("Optimizer: Running baseline backtest...")
        baseline = self.backtester.run(base_params)
        baseline_summary = {
            "label": "Current (Baseline)",
            "params": self._params_dict(base_params),
            "total_return": baseline.total_return,
            "cagr": baseline.cagr,
            "max_drawdown": baseline.max_drawdown,
            "sharpe_ratio": baseline.sharpe_ratio,
            "win_rate": baseline.win_rate,
            "total_trades": baseline.total_trades,
            "profit_factor": baseline.profit_factor,
            "final_value": baseline.final_value,
        }

        all_results = [baseline_summary]

        for round_num in range(rounds):
            # Step 2: Claude가 파라미터 제안
            if self._claude:
                suggestions = self._get_claude_suggestions(base_params, baseline)
            else:
                suggestions = self._get_default_variations(base_params)

            # Step 3: 각 제안으로 백테스트
            for i, suggestion in enumerate(suggestions):
                label = suggestion.pop("label", f"Variation {i+1}")
                try:
                    test_params = self._apply_suggestion(base_params, suggestion)
                    logger.info(f"Optimizer: Backtesting '{label}'...")
                    result = self.backtester.run(test_params)

                    all_results.append({
                        "label": label,
                        "params": self._params_dict(test_params),
                        "total_return": result.total_return,
                        "cagr": result.cagr,
                        "max_drawdown": result.max_drawdown,
                        "sharpe_ratio": result.sharpe_ratio,
                        "win_rate": result.win_rate,
                        "total_trades": result.total_trades,
                        "profit_factor": result.profit_factor,
                        "final_value": result.final_value,
                    })
                except Exception as e:
                    logger.error(f"Backtest '{label}' failed: {e}")
                    all_results.append({
                        "label": label,
                        "params": suggestion,
                        "error": str(e),
                    })

            # Update base for next round (use best sharpe)
            valid = [r for r in all_results if "sharpe_ratio" in r]
            if valid:
                best = max(valid, key=lambda r: r["sharpe_ratio"])
                # Don't actually update base_params for subsequent rounds
                # just track the best

        # Step 4: 결과 정리
        valid_results = [r for r in all_results if "sharpe_ratio" in r]
        best_sharpe = max(valid_results, key=lambda r: r["sharpe_ratio"]) if valid_results else None
        best_return = max(valid_results, key=lambda r: r["total_return"]) if valid_results else None
        lowest_dd = min(valid_results, key=lambda r: abs(r["max_drawdown"])) if valid_results else None

        elapsed = time.time() - total_start

        report = {
            "status": "completed",
            "rounds": rounds,
            "period": f"{start_date} ~ {end_date}",
            "total_variations": len(all_results),
            "elapsed_sec": round(elapsed, 1),
            "baseline": baseline_summary,
            "results": all_results,
            "recommendations": {
                "best_sharpe": best_sharpe,
                "best_return": best_return,
                "lowest_drawdown": lowest_dd,
            },
            "mode": "claude" if self._claude else "default_variations",
        }

        logger.info(f"Optimization done: {len(all_results)} variants in {elapsed:.1f}s. "
                     f"Best Sharpe: {best_sharpe['sharpe_ratio'] if best_sharpe else 'N/A'}")

        return report

    def _load_current_params(self, start_date: date, end_date: date,
                             initial_capital: float) -> BacktestParams:
        """DB swing_config에서 현재 파라미터 로드."""
        g = lambda k, d: self.pg.get_config_value(k, d)
        return BacktestParams(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            sma_short=int(g("sma_short", "50")),
            sma_long=int(g("sma_long", "200")),
            return_rank_min=float(g("return_rank_min", "0.6")),
            volume_ratio_min=float(g("volume_ratio_min", "1.2")),
            stop_loss_pct=float(g("stop_loss_pct", "-0.05")),
            take_profit_pct=float(g("take_profit_pct", "0.10")),
            max_positions=int(g("max_positions", "4")),
            position_pct=float(g("position_pct", "0.05")),
            price_range_min=float(g("price_range_min", "20")),
            price_range_max=float(g("price_range_max", "250")),
        )

    @staticmethod
    def _params_dict(p: BacktestParams) -> dict:
        return {
            "sma_short": p.sma_short, "sma_long": p.sma_long,
            "return_rank_min": p.return_rank_min,
            "volume_ratio_min": p.volume_ratio_min,
            "stop_loss_pct": p.stop_loss_pct,
            "take_profit_pct": p.take_profit_pct,
            "max_positions": p.max_positions,
            "position_pct": p.position_pct,
            "price_range_min": p.price_range_min,
            "price_range_max": p.price_range_max,
        }

    def _get_claude_suggestions(self, params: BacktestParams,
                                baseline) -> list[dict]:
        """Claude에게 파라미터 세트 5개 요청."""
        prompt = OPTIMIZE_PROMPT.format(
            current_params=json.dumps(self._params_dict(params), indent=2),
            period=f"{params.start_date} ~ {params.end_date}",
            total_return=f"{baseline.total_return:.2%}",
            cagr=f"{baseline.cagr:.2%}",
            max_drawdown=f"{baseline.max_drawdown:.2%}",
            sharpe=f"{baseline.sharpe_ratio:.4f}",
            win_rate=f"{baseline.win_rate:.2%}",
            total_trades=baseline.total_trades,
            profit_factor=f"{baseline.profit_factor:.2f}",
        )

        try:
            response = self._claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            import re
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                suggestions = json.loads(match.group())
            else:
                suggestions = json.loads(text)

            logger.info(f"Claude suggested {len(suggestions)} parameter sets")
            return suggestions[:5]

        except Exception as e:
            logger.error(f"Claude optimization request failed: {e}")
            return self._get_default_variations(params)

    @staticmethod
    def _get_default_variations(params: BacktestParams) -> list[dict]:
        """Claude 없을 때 기본 변형 5개."""
        return [
            {"label": "Tighter stops", "stop_loss_pct": -0.03,
             "take_profit_pct": 0.08},
            {"label": "Wider targets", "stop_loss_pct": -0.07,
             "take_profit_pct": 0.20},
            {"label": "More selective", "return_rank_min": 0.8,
             "volume_ratio_min": 2.0},
            {"label": "More positions", "max_positions": 6,
             "position_pct": 0.08},
            {"label": "Short SMAs", "sma_short": 30, "sma_long": 150,
             "return_rank_min": 0.5},
        ]

    @staticmethod
    def _apply_suggestion(base: BacktestParams, suggestion: dict) -> BacktestParams:
        """suggestion dict를 base params에 적용."""
        params = BacktestParams(
            start_date=base.start_date,
            end_date=base.end_date,
            initial_capital=base.initial_capital,
            sma_short=int(suggestion.get("sma_short", base.sma_short)),
            sma_long=int(suggestion.get("sma_long", base.sma_long)),
            return_rank_min=float(suggestion.get("return_rank_min", base.return_rank_min)),
            volume_ratio_min=float(suggestion.get("volume_ratio_min", base.volume_ratio_min)),
            stop_loss_pct=float(suggestion.get("stop_loss_pct", base.stop_loss_pct)),
            take_profit_pct=float(suggestion.get("take_profit_pct", base.take_profit_pct)),
            max_positions=int(suggestion.get("max_positions", base.max_positions)),
            position_pct=float(suggestion.get("position_pct", base.position_pct)),
            price_range_min=float(suggestion.get("price_range_min", base.price_range_min)),
            price_range_max=float(suggestion.get("price_range_max", base.price_range_max)),
        )
        # sma_short < sma_long 보장
        if params.sma_short >= params.sma_long:
            params.sma_short = params.sma_long - 50
        return params
