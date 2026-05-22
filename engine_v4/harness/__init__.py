"""Phase 3 — Autonomous Evolution Harness.

Components:
  - knowledge.py        Knowledge base CRUD
  - seed_data.py        Classic strategy seed (Dalio, Faber, O'Neil, Wyckoff, Tetlock, etc.)
  - researcher.py       Weekly external research (arxiv, SSRN, Quantpedia, Reddit)
  - variant_generator.py Monthly LLM-driven strategy variants
  - auto_backtest.py    Multi-period validation (90/180/365d)
  - auto_deploy.py      Safe variant deployment + rollback monitoring
  - regime_switcher.py  Macro-adaptive strategy switching
"""
