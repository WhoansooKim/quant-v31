#!/usr/bin/env bash
# VirtualBox 공유 폴더 'work' 를 /mnt/share 에 부팅 시 자동 마운트한다.
#
# 배경 (2026-09-04, §22.AO-28): VirtualBox 7.0 자동 마운트가 vboxsf 에 'tag' 옵션을 넘기는데
#   커널 드라이버가 이를 몰라 매 부팅마다 "vboxsf: Unknown parameter 'tag'" 로 실패한다.
#
# 왜 fstab 이 아니라 systemd 유닛인가 (2026-09-13 실측):
#   fstab 경로는 mount(8) → /usr/sbin/mount.vboxsf 헬퍼로 옵션이 그대로 넘어가는데,
#   이 헬퍼는 자체 파서라 nofail/_netdev/x-systemd.automount 같은 범용 옵션을 거부한다
#   ("unknown mount option `nofail'"). vboxsf 가 받는 것은 uid/gid/dmode/fmode/umask 정도뿐.
#   그래서 fstab 대신, 지금 실제로 동작하는 mount 명령 그대로를 실행하는 유닛을 쓴다.
#
# 멱등: 이미 설치돼 있으면 갱신만 한다. 검증 실패 시 유닛을 제거하고 수동 마운트로 원복한다.
set -euo pipefail

SHARE=work
MNT=/mnt/share
UID_N=1000
GID_N=1000
UNIT=/etc/systemd/system/mnt-share-vbox.service

[ "$(id -u)" -eq 0 ] || { echo "🔴 root 로 실행해야 합니다: sudo $0"; exit 1; }

mount_cmd() { mount -t vboxsf -o "uid=${UID_N},gid=${GID_N}" "$SHARE" "$MNT"; }

echo "  유닛 작성: $UNIT"
cat > "$UNIT" <<UNITEOF
[Unit]
Description=Mount VirtualBox shared folder '${SHARE}' at ${MNT}
Documentation=https://github.com/WhoansooKim/quant-v31 project_status.md §22.AO-28
# 게스트 애디션 서비스가 올라온 뒤에 마운트해야 한다
After=vboxadd-service.service
Wants=vboxadd-service.service
ConditionVirtualization=oracle

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/mkdir -p ${MNT}
# 이미 마운트돼 있으면 건너뛴다(멱등). 실패해도 부팅은 계속된다(oneshot 서비스).
ExecStart=/bin/sh -c 'mountpoint -q ${MNT} || mount -t vboxsf -o uid=${UID_N},gid=${GID_N} ${SHARE} ${MNT}'
ExecStop=/bin/sh -c 'mountpoint -q ${MNT} && umount ${MNT} || true'

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable mnt-share-vbox.service >/dev/null 2>&1
echo "  enable 완료"

echo "  --- 검증: 실제로 풀었다가 유닛으로 다시 올려본다 ---"
mountpoint -q "$MNT" && { umount "$MNT" && echo "  기존 마운트 해제"; } || true

if systemctl start mnt-share-vbox.service && mountpoint -q "$MNT"; then
  echo "✅ 성공 — 유닛이 ${MNT} 를 마운트했습니다"
  findmnt -no SOURCE,FSTYPE,OPTIONS "$MNT" | sed 's/^/   /'
  echo "   부팅 시 자동 실행: $(systemctl is-enabled mnt-share-vbox.service)"
  ls -la "$MNT" 2>/dev/null | head -6 | sed 's/^/   /'
else
  echo "🔴 실패 — 유닛을 제거하고 수동 마운트로 원복합니다"
  systemctl disable mnt-share-vbox.service >/dev/null 2>&1 || true
  rm -f "$UNIT"
  systemctl daemon-reload
  mountpoint -q "$MNT" || mount_cmd 2>/dev/null && echo "  (수동 마운트로 원상 복구했습니다)" \
    || echo "  ⚠️ 수동 마운트도 실패 — 호스트의 공유 폴더 설정을 확인하세요"
  exit 1
fi
