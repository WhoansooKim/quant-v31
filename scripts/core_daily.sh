#!/usr/bin/env bash
# 코어 일일 보고/배분 경보 (2026-11-22, 은퇴한 스윙 감시기 exit_watch·payoff·ao26 대체).
# cron: 50 0 * * 2-6 core_daily.sh alloc   /   15 7 * * 2-6 core_daily.sh summary
set -uo pipefail
export PYTHONPATH=/home/quant/quant-v31
exec /home/quant/miniconda3/envs/quant-v31/bin/python /home/quant/quant-v31/scripts/core_daily.py "$@"
