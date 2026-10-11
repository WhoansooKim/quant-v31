#!/usr/bin/env bash
# 6시간 감시 래퍼 (§22.AO-43). cron: 0 */6 * * *
# 변화가 없으면 발송하지 않는다 — 빈 보고 반복은 §22.AO-28 의 양치기 소년이 된다.
set -uo pipefail
export PYTHONPATH=/home/quant/quant-v31
exec /home/quant/miniconda3/envs/quant-v31/bin/python \
     /home/quant/quant-v31/scripts/exit_watch.py "$@"
