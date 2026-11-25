#!/usr/bin/env bash
# 🔴 RETIRED 2026-11-22 (텔레그램 정리) — 스윙 은퇴 후 의미 없는 지표를 재서 오탐을 보냈다. scripts/retired/README.md 참고.
echo "retired 2026-11-22 — scripts/retired/README.md" >&2; exit 0
# 6시간 감시 래퍼 (§22.AO-43). cron: 0 */6 * * *
# 변화가 없으면 발송하지 않는다 — 빈 보고 반복은 §22.AO-28 의 양치기 소년이 된다.
set -uo pipefail
export PYTHONPATH=/home/quant/quant-v31
exec /home/quant/miniconda3/envs/quant-v31/bin/python \
     /home/quant/quant-v31/scripts/exit_watch.py "$@"
