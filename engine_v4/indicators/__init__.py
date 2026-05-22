"""Phase 3G — Extended Technical Indicators.

Pure pandas/numpy implementations (no ta-lib dependency).
Each function takes a DataFrame with OHLCV columns and returns Series or dict.

Modules:
  - macd.py        MACD (12,26,9)
  - bollinger.py   Bollinger Bands + %B + Bandwidth
  - adx.py         ADX + DI+ / DI-
  - ichimoku.py    Ichimoku Cloud (Tenkan/Kijun/Senkou A/B/Chikou)
  - vwap.py        VWAP (rolling + anchored)
  - wyckoff.py     Volume Spread Analysis (Spring, Upthrust, Effort vs Result)
  - compute.py     Orchestrator — compute all + persist to swing_indicators
"""
