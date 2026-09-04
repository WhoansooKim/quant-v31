#!/usr/bin/env bash
# VirtualBox 공유 폴더 'work' 를 /mnt/share 에 부팅 시 자동 마운트하도록 fstab 에 등록한다.
#
# 배경 (2026-09-04, §22.AO-28): VirtualBox 7.0 의 자동 마운트가 vboxsf 에 'tag' 옵션을 넘기는데
#   커널 드라이버가 이를 모른다 — 매 부팅마다 "vboxsf: Unknown parameter 'tag'" 로 실패했다.
#   fstab 에서 직접 마운트하면 그 옵션을 쓰지 않으므로 정상 동작한다.
# 멱등: 이미 등록돼 있으면 아무것도 하지 않는다. 실패 시 fstab 을 원복한다.
set -euo pipefail

SHARE=work
MNT=/mnt/share
UID_N=1000
GID_N=1000
LINE="${SHARE}  ${MNT}  vboxsf  uid=${UID_N},gid=${GID_N},nofail,_netdev,x-systemd.automount  0  0"

[ "$(id -u)" -eq 0 ] || { echo "🔴 root 로 실행해야 합니다: sudo $0"; exit 1; }

if grep -qE "^\s*${SHARE}\s+${MNT}\s+vboxsf" /etc/fstab; then
  echo "✅ 이미 등록돼 있습니다 — 변경 없음"
  grep -nE "^\s*${SHARE}\s+${MNT}\s+vboxsf" /etc/fstab | sed 's/^/   /'
  exit 0
fi

BAK=/etc/fstab.bak.$(date +%Y%m%d%H%M%S)
cp -a /etc/fstab "$BAK"
echo "  fstab 백업: $BAK"

mkdir -p "$MNT"
printf '\n# VirtualBox 공유 폴더 (2026-09-04 추가, §22.AO-28 — VBox 자동마운트가 tag 옵션으로 실패해 수동 등록)\n%s\n' "$LINE" >> /etc/fstab
echo "  추가된 줄: $LINE"

# 검증: 이미 마운트돼 있으면 풀고 fstab 기준으로 다시 올려본다
echo "  --- 검증 ---"
mountpoint -q "$MNT" && { umount "$MNT" && echo "  기존 마운트 해제"; } || true
if systemctl daemon-reload && mount -a && mountpoint -q "$MNT"; then
  echo "✅ 성공 — $MNT 마운트됨"
  ls -la "$MNT" | head -8 | sed 's/^/   /'
else
  echo "🔴 마운트 실패 — fstab 을 원복합니다"
  cp -a "$BAK" /etc/fstab
  systemctl daemon-reload || true
  mount -t vboxsf -o "uid=${UID_N},gid=${GID_N}" "$SHARE" "$MNT" 2>/dev/null \
    && echo "  (수동 마운트로 원상 복구했습니다)" || echo "  ⚠️ 수동 마운트도 실패 — 공유 폴더 설정을 확인하세요"
  exit 1
fi
