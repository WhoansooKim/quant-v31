"""3J: 신호 표현식 엔진 (§22.AO-22).

**설계 원칙 — 임의 코드 실행 경로를 만들지 않는다.**
LLM 이 파이썬을 자유롭게 쓰게 하면 실거래 자금을 다루는 시스템에 위험하다.
대신 **화이트리스트 연산자만 허용하는 제한 수식 언어**로 신호를 표현하게 하고,
파서가 AST 를 검증해 허용 노드 외에는 전부 거부한다. `eval()` 을 쓰지 않고
검증된 AST 를 직접 순회 평가한다.

2026-08-19 ④에서 손으로 구현한 Alpha191 신호들이 정확히 이 형태였다:
    dev24       = -(close / ts_mean(close, 24) - 1)
    obv20       = ts_delta(cumsum(sign(ret) * volume), 20)
    volret_corr = -ts_corr(pct_change(volume), ret, 6)
"""

from __future__ import annotations

import ast
import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 수식에서 참조 가능한 데이터 컬럼
ALLOWED_NAMES = {"open", "high", "low", "close", "volume", "ret", "vwap", "amount"}

# 허용 함수 — 시계열/원소 연산만. I/O·속성접근·임의 호출은 파서가 거부한다.
def _ts(fn):
    return fn


ALLOWED_FUNCS: dict[str, Any] = {
    "ts_mean":    lambda x, n: x.rolling(int(n)).mean(),
    "ts_std":     lambda x, n: x.rolling(int(n)).std(),
    "ts_sum":     lambda x, n: x.rolling(int(n)).sum(),
    "ts_min":     lambda x, n: x.rolling(int(n)).min(),
    "ts_max":     lambda x, n: x.rolling(int(n)).max(),
    "ts_delta":   lambda x, n: x - x.shift(int(n)),
    "ts_corr":    lambda x, y, n: x.rolling(int(n)).corr(y),
    "ts_rank":    lambda x, n: x.rolling(int(n)).apply(
                      lambda w: pd.Series(w).rank().iloc[-1] / len(w), raw=True),
    "delay":      lambda x, n: x.shift(int(n)),
    "pct_change": lambda x, n=1: x.pct_change(int(n)),
    "cumsum":     lambda x: x.cumsum(),
    "ema":        lambda x, n: x.ewm(span=int(n), adjust=False).mean(),
    "sign":       lambda x: np.sign(x),
    "abs":        lambda x: x.abs() if hasattr(x, "abs") else abs(x),
    "log":        lambda x: np.log(x.clip(lower=1e-9) if hasattr(x, "clip") else max(x, 1e-9)),
    "sqrt":       lambda x: np.sqrt(x.clip(lower=0) if hasattr(x, "clip") else max(x, 0)),
    "clip":       lambda x, lo, hi: x.clip(lower=lo, upper=hi),
    "min":        lambda x, y: np.minimum(x, y),
    "max":        lambda x, y: np.maximum(x, y),
}

_BINOPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**"}


class FormulaError(ValueError):
    """수식이 화이트리스트를 벗어남."""


def validate(expression: str) -> ast.AST:
    """AST 를 파싱하고 허용 노드만 있는지 검사. 위반 시 FormulaError."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"파싱 실패: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Constant, ast.UnaryOp,
                             ast.UAdd, ast.USub, ast.Load)):
            continue
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _BINOPS:
                raise FormulaError(f"허용되지 않은 연산자: {type(node.op).__name__}")
            continue
        if isinstance(node, tuple(_BINOPS)):
            continue
        if isinstance(node, ast.Name):
            if node.id not in ALLOWED_NAMES and node.id not in ALLOWED_FUNCS:
                raise FormulaError(f"허용되지 않은 이름: {node.id}")
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
                raise FormulaError(f"허용되지 않은 함수 호출: {ast.dump(node.func)[:60]}")
            if node.keywords:
                raise FormulaError("키워드 인자 금지")
            continue
        raise FormulaError(f"허용되지 않은 구문: {type(node).__name__}")
    return tree


def _eval_node(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env)
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise FormulaError("숫자 상수만 허용")
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise FormulaError(f"미정의 이름: {node.id}")
    if isinstance(node, ast.UnaryOp):
        v = _eval_node(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.BinOp):
        a, b = _eval_node(node.left, env), _eval_node(node.right, env)
        op = type(node.op)
        if op is ast.Add:
            return a + b
        if op is ast.Sub:
            return a - b
        if op is ast.Mult:
            return a * b
        if op is ast.Div:
            return a / b
        if op is ast.Pow:
            return a ** b
        raise FormulaError(f"연산자 미지원: {op.__name__}")
    if isinstance(node, ast.Call):
        fn = ALLOWED_FUNCS[node.func.id]
        args = [_eval_node(a, env) for a in node.args]
        return fn(*args)
    raise FormulaError(f"평가 불가 노드: {type(node).__name__}")


def evaluate(expression: str, df: pd.DataFrame) -> pd.Series:
    """한 종목의 OHLCV DataFrame 에 수식을 적용해 Series 반환."""
    tree = validate(expression)
    c = df["close"].astype(float)
    env = {
        "open": df["open"].astype(float),
        "high": df["high"].astype(float),
        "low": df["low"].astype(float),
        "close": c,
        "volume": df["volume"].astype(float),
        "ret": c.pct_change(),
        "vwap": (df["high"].astype(float) + df["low"].astype(float) + c) / 3,
        "amount": c * df["volume"].astype(float),
    }
    out = _eval_node(tree, env)
    if not isinstance(out, pd.Series):
        raise FormulaError("결과가 시계열이 아님 (상수식 의심)")
    return out.replace([np.inf, -np.inf], np.nan)
