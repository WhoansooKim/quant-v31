#!/usr/bin/env bash
# quant-engine-v4.service 갱신 — graceful shutdown 무한 대기 제거 (§22.AO-32).
# 배경: uvicorn 이 종료 시 열린 연결(대시보드 SSE)이 닫히기를 무한정 기다려
#   SIGTERM 이 먹지 않았다. 재시작마다 kill -9 가 필요했다(2026-09-25 실측).
# 멱등: 이미 적용돼 있으면 건드리지 않는다. 실패 시 백업본으로 원복한다.
set -euo pipefail
SRC=/home/quant/quant-v31/systemd/quant-engine-v4.service
DST=/etc/systemd/system/quant-engine-v4.service

[ "$(id -u)" -eq 0 ] || { echo "🔴 root 로 실행해야 합니다: sudo $0"; exit 1; }
[ -f "$SRC" ] || { echo "🔴 저장소 유닛 파일이 없습니다: $SRC"; exit 1; }

if diff -q "$SRC" "$DST" >/dev/null 2>&1; then
  echo "✅ 이미 최신 — 변경 없음"; exit 0
fi

BAK="${DST}.bak.$(date +%Y%m%d%H%M%S)"
cp -a "$DST" "$BAK"; echo "  백업: $BAK"
cp -a "$SRC" "$DST"
systemctl daemon-reload
echo "  적용된 차이:"; diff -u "$BAK" "$DST" | sed -n '3,$p' | sed 's/^/    /' || true

echo "  --- 검증: 재시작 소요시간 측정 ---"
T0=$(date +%s)
if timeout 90 systemctl restart quant-engine-v4; then
  T1=$(date +%s)
  for _ in $(seq 1 30); do
    curl -sf -m 5 http://localhost:8001/health >/dev/null 2>&1 && break
    sleep 2
  done
  echo "✅ 재시작 성공 — 정지+기동 $((T1-T0))초 (이전: 무한 대기 → kill -9 필요)"
  systemctl is-active quant-engine-v4 | sed 's/^/   상태: /'
  curl -s -m 10 http://localhost:8001/health | sed 's/^/   /'
else
  echo "🔴 재시작 실패 — 유닛을 원복합니다"
  cp -a "$BAK" "$DST"; systemctl daemon-reload
  systemctl restart quant-engine-v4 || true
  exit 1
fi
