import { useState } from "react";

const C = {
  bg: "#05060b", s1: "#0a0c15", s2: "#0f111c", s3: "#141729",
  bd: "#1c2040", t: "#a8afc4", tm: "#555d78", tb: "#dde1ed", tw: "#f0f2f8",
  emerald: "#10b981", blue: "#3b82f6", violet: "#8b5cf6",
  amber: "#f59e0b", rose: "#f43f5e", cyan: "#06b6d4",
  orange: "#f97316", lime: "#84cc16", pink: "#ec4899",
};

const Sec = ({ children, c = C.blue }) => (
  <div style={{ fontWeight: 800, color: C.tb, fontSize: 14, margin: "22px 0 10px", paddingBottom: 7,
    borderBottom: `2px solid ${c}28`, display: "flex", alignItems: "center", gap: 8 }}>
    <div style={{ width: 3, height: 16, background: c, borderRadius: 2 }} />{children}
  </div>
);
const Info = ({ c, icon, title, children }) => (
  <div style={{ background: `${c}06`, border: `1px solid ${c}18`, borderRadius: 10, padding: "12px 14px", margin: "10px 0" }}>
    <div style={{ color: c, fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{icon} {title}</div>
    <div style={{ color: C.t, fontSize: 11.5, lineHeight: 1.75 }}>{children}</div>
  </div>
);
const Warn = ({ children }) => (
  <div style={{ background: "#f59e0b08", border: "1px solid #f59e0b20", borderRadius: 8, padding: "10px 12px",
    margin: "8px 0", fontSize: 11, color: C.amber, lineHeight: 1.7 }}>⚠️ {children}</div>
);
const Pre = ({ children }) => (
  <pre style={{ color: C.emerald, fontSize: 9.5, lineHeight: 1.55,
    fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace",
    margin: "6px 0", overflowX: "auto", whiteSpace: "pre", padding: "12px 14px",
    background: "#04050a", borderRadius: 8, border: `1px solid ${C.bd}` }}>{children}</pre>
);
const Step = ({ n, title, c = C.blue }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "18px 0 8px" }}>
    <span style={{ background: c, color: "#fff", width: 24, height: 24, borderRadius: "50%",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 12, fontWeight: 800, flexShrink: 0 }}>{n}</span>
    <span style={{ color: C.tw, fontWeight: 700, fontSize: 13 }}>{title}</span>
  </div>
);
const Chk = ({ items, c = C.emerald }) => items.map((x, i) => (
  <div key={i} style={{ display: "flex", gap: 8, padding: "4px 0", fontSize: 11, color: C.t }}>
    <span style={{ color: c, flexShrink: 0 }}>☐</span><span>{x}</span>
  </div>
));

// ═══════════════════════════════════════════════════════════════
// PAGES
// ═══════════════════════════════════════════════════════════════

function VBoxSetup() {
  return (<div>
    <Info c={C.blue} icon="📦" title="Step 1: VirtualBox + Ubuntu VM 생성">
      Windows 10 (64GB RAM) 위에 VirtualBox로 Ubuntu 24.04 LTS VM을 생성합니다. 개발에 최적화된 설정으로 구성합니다.
    </Info>

    <Sec c={C.blue}>1-1. VirtualBox 설치</Sec>
    <Step n="1" title="VirtualBox 다운로드 + 설치" />
    <Pre>{`# 1. 다운로드
https://www.virtualbox.org/wiki/Downloads
→ "Windows hosts" 클릭 → 최신 버전 설치

# 2. Extension Pack도 설치 (USB 3.0, 디스크 암호화 등)
같은 페이지 → "Oracle VirtualBox Extension Pack"
→ 다운로드 후 더블클릭하면 VirtualBox가 자동 설치`}</Pre>

    <Step n="2" title="Windows 사전 설정: Hyper-V 확인" />
    <Warn>
      Windows에서 <b>Hyper-V</b>가 활성화되어 있으면 VirtualBox 성능이 크게 저하됩니다.
      Docker Desktop을 사용 중이라면 Hyper-V가 켜져 있을 수 있습니다.
      <br /><br />
      <b>확인 방법:</b> PowerShell(관리자) → <code>systeminfo</code> → "Hyper-V 요구 사항" 확인
      <br />
      <b>비활성화:</b> 제어판 → 프로그램 → Windows 기능 → Hyper-V 체크 해제 → 재부팅
      <br /><br />
      Docker Desktop은 VM 안의 Ubuntu에서 Docker Engine을 사용하므로 호스트에서 불필요합니다.
    </Warn>

    <Sec c={C.cyan}>1-2. Ubuntu ISO 다운로드</Sec>
    <Pre>{`# Ubuntu 24.04.x LTS Server (권장) 또는 Desktop
https://ubuntu.com/download/server
→ "Ubuntu Server 24.04 LTS" 다운로드 (~2.5GB)

# Server vs Desktop 선택:
# Server (★ 권장): GUI 없음, 리소스 절약, SSH 접속
#   → 메모리 ~500MB만 사용 (나머지 전부 Docker/PG에)
#   → VS Code Remote-SSH로 호스트 Windows에서 편집
#
# Desktop: GUI 있음, 메모리 ~2GB 추가 소모
#   → VM 안에서 직접 브라우저, 에디터 사용 가능`}</Pre>

    <Sec c={C.violet}>1-3. VM 생성 (최적 설정)</Sec>
    <Step n="3" title="VirtualBox에서 새 VM 만들기" />
    <Pre>{`VirtualBox 메인 → "새로 만들기" 클릭

# ── 기본 정보 ──
이름: quant-v31-dev
폴더: D:\\VirtualBox VMs    (또는 여유 디스크)
ISO 이미지: (다운로드한 ubuntu-24.04-server.iso 선택)
유형: Linux
버전: Ubuntu (64-bit)
☑ "무인 설치 건너뛰기" 체크 (수동 설치 권장)`}</Pre>

    <Step n="4" title="하드웨어 설정" c={C.emerald} />
    <Pre>{`# ── 메모리 ──
기본 메모리: 32768 MB (32 GB)
  → 호스트 64GB 중 32GB 할당
  → 호스트에 32GB 여유 (현재 26% 사용 = 충분)

# ── CPU ──
프로세서: 호스트 코어의 70~80%
  → 예: 8코어 CPU면 6코어 할당
  → 예: 12코어/24스레드면 8~10 할당
실행 상한: 100%
☑ "PAE/NX 사용하기" 체크
☑ "VT-x/AMD-V 중첩 사용" 체크 (★ Docker 성능에 중요)`}</Pre>

    <Step n="5" title="디스크 설정" c={C.amber} />
    <Pre>{`# ── 가상 하드 디스크 ──
"지금 새 가상 하드 디스크 만들기" 선택
파일 크기: 200 GB (15년 데이터 + Docker + 여유)
형태: VDI (VirtualBox Disk Image)

★★★ 중요: "사전 할당 전체 크기" 선택 ★★★
  → "동적 할당"보다 디스크 I/O가 30% 빠름
  → 200GB 공간을 미리 확보함
  → PostgreSQL, Parquet 대용량 데이터에 필수`}</Pre>

    <Warn>
      디스크 200GB는 실제 호스트 디스크 공간을 즉시 차지합니다. 호스트에 <b>300GB+ 여유 공간</b>이 있는 드라이브에 VM을 생성하세요. SSD라면 더 좋습니다.
    </Warn>

    <Step n="6" title="VM 설정 세부 조정" c={C.violet} />
    <Pre>{`# VM 생성 후 → "설정" 클릭

# ── 시스템 → 마더보드 ──
부팅 순서: 광학 → 하드디스크 (플로피 제거)
☑ "EFI 사용하기" 체크 (UEFI 부팅, 최신 권장)
칩셋: ICH9

# ── 시스템 → 프로세서 ──
(이미 설정됨)

# ── 디스플레이 ──
비디오 메모리: 128 MB (Server면 16MB도 OK)
그래픽 컨트롤러: VMSVGA

# ── 저장소 ──
컨트롤러: SATA
  → VDI 디스크 선택 → ★ "Host I/O 캐시 사용" 체크
  → 호스트 캐시가 디스크 I/O 성능을 크게 향상

# ── 네트워크 ──
어댑터 1:
  ★ "브릿지 어댑터" 선택 (NAT 아님!)
  이름: (호스트의 실제 네트워크 어댑터)
  
  브릿지 어댑터 장점:
  → VM이 호스트와 같은 네트워크에 독립 IP 획득
  → 호스트 브라우저에서 http://VM_IP:5000 접속 가능
  → 다른 PC/모바일에서도 Blazor 대시보드 접속 가능

# ── 공유 폴더 (선택) ──
폴더 경로: D:\\work\\95.Study\\17.regime_adaptive_quantsystem
폴더 이름: quant-share
☑ "자동 마운트"
마운트 위치: /mnt/share`}</Pre>

    <Sec c={C.emerald}>1-4. Ubuntu 설치</Sec>
    <Step n="7" title="Ubuntu Server 설치 진행" c={C.emerald} />
    <Pre>{`# VM 시작 → Ubuntu ISO 부팅

# 설치 과정 (Server 기준):
1. 언어: English (한국어 선택 가능하나 Server는 English 권장)
2. 키보드: Korean (101/104) 또는 English (US)
3. 설치 유형: "Ubuntu Server" (minimized 아님)
4. 네트워크: 자동 (브릿지면 DHCP로 IP 자동 할당)
5. 프록시: 비워두기
6. 미러: 기본값 (kr.archive.ubuntu.com)
7. 디스크: "Use an entire disk" → ★ LVM 사용
8. 프로필:
   이름: quant
   서버 이름: quant-dev
   사용자: quant
   비밀번호: (설정)
9. ★ SSH: "Install OpenSSH server" 체크!
10. 추가 패키지: 없음 (나중에 설치)
11. 설치 완료 → "Reboot Now"

# 재부팅 후 로그인
quant-dev login: quant
Password: (설정한 비밀번호)`}</Pre>

    <Step n="8" title="설치 후 IP 확인" c={C.orange} />
    <Pre>{`# VM 터미널에서
ip addr show
# → enp0s3 (또는 비슷한 이름)에서 inet 192.168.x.x 확인

# 이제부터 호스트 Windows에서 SSH로 접속 가능!
# Windows PowerShell에서:
ssh quant@192.168.x.x

# 또는 VS Code → Remote-SSH 확장 설치 후 접속 (★ 강력 추천)`}</Pre>

    <Info c={C.lime} icon="💡" title="VS Code Remote-SSH 추천">
      호스트 Windows의 VS Code에서 VM에 SSH 접속하면:<br />
      • Windows에서 코드 편집 → VM에서 실행 (최고의 개발 경험)<br />
      • 파일 탐색기, 터미널, 디버거 모두 VM에 직접 연결<br />
      • VM에 GUI(Desktop) 불필요 → 메모리 2GB 절약
    </Info>

    <Sec c={C.rose}>1-5. 체크리스트</Sec>
    <Chk items={[
      "VirtualBox + Extension Pack 설치",
      "Hyper-V 비활성화 확인",
      "Ubuntu 24.04 LTS Server ISO 다운로드",
      "VM 생성: 32GB RAM, 6~10 CPU 코어, 200GB 고정 VDI",
      "네트워크: 브릿지 어댑터 설정",
      "디스크: Host I/O 캐시 활성화",
      "Ubuntu 설치 완료 + SSH 서버 활성화",
      "호스트에서 ssh quant@VM_IP 접속 성공",
      "VS Code Remote-SSH 연결 성공",
    ]} />
  </div>);
}

function UbuntuBase() {
  return (<div>
    <Info c={C.cyan} icon="🐧" title="Step 2: Ubuntu 기본 설정 + 필수 패키지">
      시스템 업데이트, 필수 도구, 보안 설정, 시간대 설정 등.
    </Info>

    <Sec c={C.cyan}>2-1. 시스템 업데이트 + 기본 패키지</Sec>
    <Pre>{`# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 필수 도구
sudo apt install -y \\
  curl wget git htop tmux tree unzip \\
  build-essential pkg-config \\
  software-properties-common \\
  apt-transport-https ca-certificates \\
  gnupg lsb-release

# 시간대 설정 (한국)
sudo timedatectl set-timezone Asia/Seoul
timedatectl  # 확인

# 호스트명 확인
hostnamectl`}</Pre>

    <Sec c={C.violet}>2-2. SSH 설정 강화</Sec>
    <Pre>{`# SSH 키 생성 (VM 안에서)
ssh-keygen -t ed25519 -C "quant-v31-dev"
# → 비밀번호 없이 Enter (개발환경)

# 호스트 Windows에서 SSH 키 복사 (PowerShell):
# ssh-keygen -t ed25519  (호스트에 키가 없으면)
# type $env:USERPROFILE\\.ssh\\id_ed25519.pub | ssh quant@VM_IP "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"

# SSH 설정 (선택: 비밀번호 로그인 비활성화)
# sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no
# sudo systemctl restart sshd`}</Pre>

    <Sec c={C.amber}>2-3. 방화벽 설정</Sec>
    <Pre>{`# UFW 활성화 + 필요 포트 열기
sudo ufw allow ssh          # 22
sudo ufw allow 5432         # PostgreSQL
sudo ufw allow 6379         # Redis
sudo ufw allow 8000         # FastAPI
sudo ufw allow 5000         # Blazor Server
sudo ufw allow 50051        # gRPC
sudo ufw enable
sudo ufw status`}</Pre>

    <Sec c={C.emerald}>2-4. VirtualBox Guest Additions (공유폴더용)</Sec>
    <Pre>{`# Guest Additions 설치 (공유폴더, 클립보드 공유에 필요)
sudo apt install -y virtualbox-guest-additions-iso
sudo apt install -y linux-headers-$(uname -r) gcc make perl

# VirtualBox 메뉴 → 장치 → "게스트 확장 CD 이미지 삽입"
sudo mount /dev/cdrom /mnt
sudo /mnt/VBoxLinuxAdditions.run
sudo umount /mnt

# 공유 폴더 접근을 위해 vboxsf 그룹 추가
sudo usermod -aG vboxsf quant

# 재부팅
sudo reboot

# 재부팅 후 공유 폴더 확인
ls /mnt/share
# → 호스트 D:\\work\\95.Study\\17.regime_adaptive_quantsystem 내용이 보임`}</Pre>

    <Sec c={C.blue}>2-5. 유용한 .bashrc 설정</Sec>
    <Pre>{`# ~/.bashrc 끝에 추가
cat >> ~/.bashrc << 'EOF'

# ─── Quant V3.1 개발환경 ───
export EDITOR=nano
export LANG=en_US.UTF-8

# 별칭
alias ll='ls -alFh --color'
alias dc='docker compose'
alias dps='docker ps --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}"'
alias dlogs='docker compose logs -f'
alias pg='docker exec -it quant-postgres psql -U quant -d quantdb'
alias redis-cli='docker exec -it quant-redis redis-cli'

# 프로젝트 경로
export QUANT_HOME=~/quant-v31
alias cdq='cd $QUANT_HOME'

# Python conda 자동 활성화 (conda 설치 후)
# conda activate quant-v31

# 색상 프롬프트
PS1='\\[\\033[1;32m\\]quant@dev\\[\\033[0m\\]:\\[\\033[1;34m\\]\\w\\[\\033[0m\\]\\$ '
EOF

source ~/.bashrc`}</Pre>

    <Sec c={C.rose}>2-6. tmux 기본 설정 (터미널 멀티플렉서)</Sec>
    <Pre>{`# tmux 설정 (SSH 끊겨도 작업 유지!)
cat > ~/.tmux.conf << 'EOF'
# 마우스 활성화
set -g mouse on

# 256색 지원
set -g default-terminal "screen-256color"

# 패널 분할 단축키
bind | split-window -h
bind - split-window -v

# 상태바
set -g status-bg colour235
set -g status-fg white
set -g status-right '#[fg=yellow]%Y-%m-%d %H:%M'
EOF

# 사용법:
# tmux new -s dev       # 새 세션
# tmux attach -t dev    # 세션 재접속
# Ctrl+b | → 세로 분할
# Ctrl+b - → 가로 분할
# Ctrl+b d → 세션 분리 (백그라운드 유지)`}</Pre>

    <Chk items={[
      "시스템 업데이트 완료",
      "시간대 Asia/Seoul 설정",
      "SSH 키 인증 설정",
      "UFW 방화벽 포트 개방 (22,5432,6379,8000,5000,50051)",
      "Guest Additions 설치 + 공유폴더 마운트",
      ".bashrc 별칭 설정 (dc, pg, redis-cli 등)",
      "tmux 설정 완료",
    ]} />
  </div>);
}

function DockerSetup() {
  return (<div>
    <Info c={C.orange} icon="🐳" title="Step 3: Docker Engine + Docker Compose + 서비스 실행">
      Docker Desktop이 아닌 <b>Docker Engine</b>(네이티브)을 설치합니다. VM Linux에서 직접 구동되어 성능이 최적입니다.
    </Info>

    <Sec c={C.orange}>3-1. Docker Engine 설치</Sec>
    <Pre>{`# 공식 Docker GPG 키 추가
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \\
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Docker 저장소 추가
echo "deb [arch=$(dpkg --print-architecture) \\
  signed-by=/etc/apt/keyrings/docker.gpg] \\
  https://download.docker.com/linux/ubuntu \\
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \\
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 설치
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \\
  docker-buildx-plugin docker-compose-plugin

# 현재 유저를 docker 그룹에 추가 (sudo 없이 docker 사용)
sudo usermod -aG docker $USER
newgrp docker

# 확인
docker --version        # Docker version 27.x.x
docker compose version  # Docker Compose version v2.3x.x
docker run hello-world  # 정상 동작 확인`}</Pre>

    <Sec c={C.cyan}>3-2. 프로젝트 디렉토리 생성</Sec>
    <Pre>{`# 프로젝트 루트
mkdir -p ~/quant-v31/{engine,dashboard,proto,scripts,data,models,systemd}
mkdir -p ~/quant-v31/data/{parquet/ohlcv,parquet/benchmark}
cd ~/quant-v31`}</Pre>

    <Sec c={C.violet}>3-3. docker-compose.yml 작성</Sec>
    <Pre>{`# ~/quant-v31/docker-compose.yml
cat > ~/quant-v31/docker-compose.yml << 'YAML'
version: "3.9"
services:

  # ── PostgreSQL 16 + TimescaleDB ──
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: quant-postgres
    environment:
      POSTGRES_DB: quantdb
      POSTGRES_USER: quant
      POSTGRES_PASSWORD: "QuantV31!Secure"
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./scripts/init_db.sql:/docker-entrypoint-initdb.d/01_init.sql
    command: >
      postgres
        -c shared_preload_libraries='timescaledb'
        -c timescaledb.telemetry_level=off
        -c max_connections=100
        -c shared_buffers=8GB
        -c effective_cache_size=24GB
        -c work_mem=256MB
        -c maintenance_work_mem=2GB
        -c wal_buffers=64MB
    shm_size: '2g'
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quant -d quantdb"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Redis 7 (캐시 전용) ──
  redis:
    image: redis:7-alpine
    container_name: quant-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s

volumes:
  pg_data:
  redis_data:
YAML`}</Pre>

    <Sec c={C.rose}>3-4. init_db.sql 작성 (TimescaleDB 스키마)</Sec>
    <Pre>{`# ~/quant-v31/scripts/init_db.sql
cat > ~/quant-v31/scripts/init_db.sql << 'SQL'
-- TimescaleDB 활성화
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 종목 마스터
CREATE TABLE symbols (
    symbol_id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    company_name VARCHAR(200),
    sector VARCHAR(50),
    industry VARCHAR(100),
    market_cap NUMERIC(18,2),
    exchange VARCHAR(10),
    is_active BOOLEAN DEFAULT true,
    meta JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_symbols_sector ON symbols(sector);

-- 일봉 가격 (Hypertable)
CREATE TABLE daily_prices (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    open NUMERIC(12,4),
    high NUMERIC(12,4),
    low NUMERIC(12,4),
    close NUMERIC(12,4),
    volume BIGINT,
    adj_close NUMERIC(12,4),
    UNIQUE(time, symbol)
);
SELECT create_hypertable('daily_prices', by_range('time'));

-- 자동 압축 (30일 후)
ALTER TABLE daily_prices SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('daily_prices', interval '30 days');

-- 레짐 히스토리 (Hypertable)
CREATE TABLE regime_history (
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    regime VARCHAR(10),
    bull_prob NUMERIC(5,4),
    sideways_prob NUMERIC(5,4),
    bear_prob NUMERIC(5,4),
    confidence NUMERIC(5,4),
    previous_regime VARCHAR(10),
    is_transition BOOLEAN DEFAULT false
);
SELECT create_hypertable('regime_history', by_range('detected_at'));

-- Kill Switch 로그
CREATE TABLE kill_switch_log (
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_level VARCHAR(15),
    to_level VARCHAR(15),
    current_mdd NUMERIC(6,4),
    portfolio_value NUMERIC(18,2),
    exposure_limit NUMERIC(4,2),
    cooldown_until TIMESTAMPTZ
);
SELECT create_hypertable('kill_switch_log', by_range('event_time'));

-- 포트폴리오 스냅샷 (Hypertable)
CREATE TABLE portfolio_snapshots (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_value NUMERIC(18,2),
    cash_value NUMERIC(18,2),
    daily_return NUMERIC(10,6),
    cumulative_return NUMERIC(10,6),
    sharpe_ratio NUMERIC(6,4),
    max_drawdown NUMERIC(6,4),
    vol_scale NUMERIC(4,2),
    regime VARCHAR(10),
    regime_confidence NUMERIC(4,3),
    kill_level VARCHAR(15),
    exposure_limit NUMERIC(4,2)
);
SELECT create_hypertable('portfolio_snapshots', by_range('time'));

-- 센티먼트 스코어 (Hypertable)
CREATE TABLE sentiment_scores (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol VARCHAR(10),
    finbert_score NUMERIC(5,3),
    claude_score NUMERIC(5,3),
    hybrid_score NUMERIC(5,3),
    source VARCHAR(20),
    headline_count INT
);
SELECT create_hypertable('sentiment_scores', by_range('time'));

-- 거래 기록
CREATE TABLE trades (
    trade_id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(50),
    symbol VARCHAR(10),
    strategy VARCHAR(50),
    side VARCHAR(5),
    qty NUMERIC(12,4),
    price NUMERIC(12,4),
    regime VARCHAR(10),
    kill_level VARCHAR(15),
    executed_at TIMESTAMPTZ DEFAULT now(),
    is_paper BOOLEAN DEFAULT true
);

-- 전략별 성과 (Hypertable)
CREATE TABLE strategy_performance (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy VARCHAR(50),
    daily_return NUMERIC(10,6),
    allocation NUMERIC(4,2),
    regime VARCHAR(10),
    signal_count INT,
    win_rate NUMERIC(4,2)
);
SELECT create_hypertable('strategy_performance', by_range('time'));

-- 시그널 로그
CREATE TABLE signal_log (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol VARCHAR(10),
    direction VARCHAR(10),
    strength NUMERIC(6,3),
    strategy VARCHAR(50),
    regime VARCHAR(10)
);
SELECT create_hypertable('signal_log', by_range('time'));

-- 재무 데이터
CREATE TABLE fundamentals (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10),
    report_date DATE DEFAULT CURRENT_DATE,
    market_cap NUMERIC(18,2),
    roe NUMERIC(8,4),
    revenue_growth NUMERIC(8,4),
    eps NUMERIC(10,4),
    debt_to_equity NUMERIC(8,4),
    free_cashflow NUMERIC(18,2),
    gross_margin NUMERIC(8,4),
    beta NUMERIC(6,4),
    extra JSONB DEFAULT '{}',
    UNIQUE(ticker, report_date)
);

-- 공적분 페어즈
CREATE TABLE cointegrated_pairs (
    pair_id SERIAL PRIMARY KEY,
    symbol1 VARCHAR(10),
    symbol2 VARCHAR(10),
    p_value NUMERIC(8,6),
    spread_zscore NUMERIC(6,2),
    is_active BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(symbol1, symbol2)
);

-- 확인용 쿼리
SELECT 'TimescaleDB version: ' || extversion FROM pg_extension WHERE extname='timescaledb';
SELECT 'Tables: ' || count(*)::text FROM information_schema.tables WHERE table_schema='public';
SQL`}</Pre>

    <Sec c={C.emerald}>3-5. Docker 서비스 시작 + 검증</Sec>
    <Pre>{`cd ~/quant-v31

# 서비스 시작
docker compose up -d

# 상태 확인
docker ps
# NAMES             STATUS               PORTS
# quant-postgres    Up (healthy)         0.0.0.0:5432->5432
# quant-redis       Up (healthy)         0.0.0.0:6379->6379

# PostgreSQL 접속 테스트
docker exec -it quant-postgres psql -U quant -d quantdb -c "
  SELECT 'PG: ' || version();
  SELECT 'TimescaleDB: ' || extversion FROM pg_extension WHERE extname='timescaledb';
  SELECT 'Hypertables: ' || count(*)::text FROM timescaledb_information.hypertables;
"

# 기대 결과:
# PG: PostgreSQL 16.x ...
# TimescaleDB: 2.x.x
# Hypertables: 7  (daily_prices, regime_history, ... 등)

# Redis 테스트
docker exec -it quant-redis redis-cli ping
# PONG

# 별칭으로 간편 접속 (bashrc에 설정한 것)
pg      # → psql 접속
# \\dt    → 테이블 목록
# \\q     → 종료`}</Pre>

    <Chk items={[
      "Docker Engine + Compose 설치 완료",
      "docker-compose.yml 작성",
      "init_db.sql 작성 (11개 테이블 + 7개 hypertable)",
      "docker compose up -d 정상 실행",
      "PostgreSQL 16 접속 성공",
      "TimescaleDB 확장 활성화 확인",
      "Hypertable 7개 생성 확인",
      "Redis ping/pong 확인",
    ]} />
  </div>);
}

function PythonSetup() {
  return (<div>
    <Info c={C.violet} icon="🐍" title="Step 4: Python 환경 + 전체 패키지 + 검증">
      Miniconda → quant-v31 환경 → 핵심 패키지 + V3.1 신규 패키지(hmmlearn, transformers, torch, shap, praw) 설치 + 연결 테스트.
    </Info>

    <Sec c={C.violet}>4-1. Miniconda 설치</Sec>
    <Pre>{`# Miniconda 다운로드 + 설치
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3

# PATH 등록
~/miniconda3/bin/conda init bash
source ~/.bashrc

# 확인
conda --version  # conda 24.x.x`}</Pre>

    <Sec c={C.blue}>4-2. conda 환경 생성 + 패키지 설치</Sec>
    <Pre>{`# 환경 생성
conda create -n quant-v31 python=3.11 -y
conda activate quant-v31

# ═══════════════════════════════════
# 핵심 데이터 + 수학
# ═══════════════════════════════════
pip install polars pandas numpy scipy scikit-learn

# ═══════════════════════════════════
# 웹 프레임워크 + API
# ═══════════════════════════════════
pip install fastapi uvicorn[standard]
pip install grpcio grpcio-tools

# ═══════════════════════════════════
# ★ PostgreSQL 드라이버 (핵심!)
# ═══════════════════════════════════
pip install "psycopg[binary]"          # psycopg3 (비동기 지원)
pip install "sqlalchemy[asyncio]"      # SQLAlchemy 2.0

# ═══════════════════════════════════
# 데이터 수집
# ═══════════════════════════════════
pip install yfinance alpaca-py fredapi
pip install pyarrow                     # Parquet

# ═══════════════════════════════════
# 백테스트 + ML
# ═══════════════════════════════════
pip install vectorbt lightgbm xgboost
pip install statsmodels

# ═══════════════════════════════════
# ★ V3.1 레짐 + 센티먼트 (신규)
# ═══════════════════════════════════
pip install hmmlearn                    # HMM 레짐 감지

# PyTorch CPU 전용 (GPU 없는 서버)
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install transformers                # FinBERT
pip install shap                        # Feature Importance
pip install praw                        # Reddit API

# ═══════════════════════════════════
# 유틸리티
# ═══════════════════════════════════
pip install anthropic                   # Claude API
pip install python-telegram-bot         # Telegram 알림
pip install apscheduler                 # 스케줄러
pip install pydantic-settings           # 설정 관리
pip install redis                       # Redis 클라이언트
pip install plotly                      # 시각화

echo "✅ 전체 패키지 설치 완료"`}</Pre>

    <Sec c={C.rose}>4-3. FinBERT 모델 다운로드</Sec>
    <Pre>{`# FinBERT 모델 사전 다운로드 (~420MB, 첫 실행 시)
python << 'PYEOF'
print("📥 FinBERT 모델 다운로드 중...")
from transformers import AutoTokenizer, AutoModelForSequenceClassification
tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
print(f"✅ FinBERT 다운로드 완료")
print(f"   모델 파라미터: {sum(p.numel() for p in model.parameters()):,}")
print(f"   저장 위치: ~/.cache/huggingface/hub/")
PYEOF`}</Pre>

    <Sec c={C.amber}>4-4. 전체 연결 테스트 스크립트</Sec>
    <Pre>{`# ~/quant-v31/scripts/verify_env.py
cat > ~/quant-v31/scripts/verify_env.py << 'PYEOF'
"""V3.1 개발환경 전체 검증 스크립트"""
import sys

def test(name, func):
    try:
        result = func()
        print(f"  ✅ {name}: {result}")
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        return False

print("=" * 60)
print("🔍 Quant V3.1 개발환경 검증")
print("=" * 60)
passed = 0
total = 0

# ── Python 버전 ──
print("\\n📦 Python")
total += 1
passed += test("Python 버전", lambda: f"{sys.version_info.major}.{sys.version_info.minor}")

# ── 핵심 패키지 ──
print("\\n📦 핵심 패키지")
for pkg in ["polars","numpy","scipy","pandas","fastapi","grpcio"]:
    total += 1
    passed += test(pkg, lambda p=pkg: __import__(p).__version__ 
                   if hasattr(__import__(p),'__version__') else "OK")

# ── PostgreSQL 연결 ──
print("\\n🐘 PostgreSQL + TimescaleDB")
total += 1
def test_pg():
    import psycopg
    conn = psycopg.connect("postgresql://quant:QuantV31!Secure@localhost:5432/quantdb")
    ver = conn.execute("SELECT version()").fetchone()[0][:40]
    conn.close()
    return ver
passed += test("PostgreSQL 연결", test_pg)

total += 1
def test_ts():
    import psycopg
    conn = psycopg.connect("postgresql://quant:QuantV31!Secure@localhost:5432/quantdb")
    ver = conn.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'").fetchone()[0]
    conn.close()
    return f"TimescaleDB {ver}"
passed += test("TimescaleDB", test_ts)

total += 1
def test_ht():
    import psycopg
    conn = psycopg.connect("postgresql://quant:QuantV31!Secure@localhost:5432/quantdb")
    cnt = conn.execute("SELECT count(*) FROM timescaledb_information.hypertables").fetchone()[0]
    conn.close()
    return f"{cnt}개 hypertable"
passed += test("Hypertables", test_ht)

# ── Redis ──
print("\\n🔴 Redis")
total += 1
def test_redis():
    import redis
    r = redis.from_url("redis://localhost:6379")
    return r.ping()
passed += test("Redis 연결", test_redis)

# ── V3.1 레짐/센티먼트 ──
print("\\n🎯 V3.1 레짐/센티먼트 패키지")
total += 1
passed += test("hmmlearn", lambda: __import__("hmmlearn").__version__)

total += 1
def test_hmm():
    from hmmlearn.hmm import GaussianHMM
    import numpy as np
    model = GaussianHMM(n_components=3, n_iter=10)
    X = np.random.randn(100, 2)
    model.fit(X)
    return f"3-State HMM OK"
passed += test("HMM 동작", test_hmm)

total += 1
passed += test("torch", lambda: __import__("torch").__version__)

total += 1
passed += test("transformers", lambda: __import__("transformers").__version__)

total += 1
def test_finbert():
    from transformers import pipeline
    nlp = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=-1)
    result = nlp("Apple reports record revenue")[0]
    return f"label={result['label']}, score={result['score']:.3f}"
passed += test("FinBERT 추론", test_finbert)

total += 1
passed += test("shap", lambda: __import__("shap").__version__)

# ── 데이터 수집 ──
print("\\n📊 데이터 수집")
total += 1
def test_yf():
    import yfinance as yf
    data = yf.download("SPY", period="5d", progress=False)
    return f"SPY {len(data)}일 데이터"
passed += test("yfinance", test_yf)

total += 1
passed += test("alpaca-py", lambda: __import__("alpaca").__name__)
total += 1
passed += test("statsmodels", lambda: __import__("statsmodels").__version__)

# ── 결과 ──
print("\\n" + "=" * 60)
pct = passed / total * 100
color = "✅" if pct == 100 else "⚠️" if pct >= 80 else "❌"
print(f"{color} 결과: {passed}/{total} 통과 ({pct:.0f}%)")
if pct == 100:
    print("🎉 개발환경 완벽! Phase 1 데이터 수집 시작 가능")
elif pct >= 80:
    print("⚠️ 일부 실패 — 실패 항목 확인 후 수정 필요")
else:
    print("❌ 다수 실패 — 패키지 재설치 필요")
print("=" * 60)
PYEOF

# 실행
cd ~/quant-v31
python scripts/verify_env.py`}</Pre>

    <Sec c={C.lime}>4-5. FinBERT CPU 벤치마크</Sec>
    <Pre>{`# ~/quant-v31/scripts/benchmark_finbert.py
cat > ~/quant-v31/scripts/benchmark_finbert.py << 'PYEOF'
"""Dell 서버 (VM) CPU에서 FinBERT 성능 측정"""
import time
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

print("📊 FinBERT CPU 벤치마크")
print(f"PyTorch: {torch.__version__}")
print(f"CPU 스레드: {torch.get_num_threads()}")

tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
model.eval()

headlines = [
    "Apple reports record quarterly revenue beating expectations",
    "Fed signals aggressive rate hikes amid persistent inflation",
    "Tesla shares plunge 12% after disappointing delivery numbers",
    "Nvidia surpasses trillion dollar valuation on AI demand",
    "Unemployment claims rise sharply to six month high",
] * 20  # 100건

print(f"\\n테스트: {len(headlines)}건 헤드라인 배치 처리")

# Warm-up
inputs = tokenizer(headlines[:5], padding=True, truncation=True, 
                    max_length=512, return_tensors="pt")
with torch.no_grad():
    model(**inputs)

# 실제 벤치마크 (3회 평균)
times = []
for trial in range(3):
    inputs = tokenizer(headlines, padding=True, truncation=True,
                       max_length=512, return_tensors="pt")
    start = time.time()
    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)
    elapsed = time.time() - start
    times.append(elapsed)
    print(f"  Trial {trial+1}: {elapsed:.2f}s ({len(headlines)/elapsed:.1f} 건/초)")

avg = sum(times) / len(times)
print(f"\\n{'='*40}")
print(f"✅ 평균: {avg:.2f}초 → {len(headlines)/avg:.1f} 건/초")
if len(headlines)/avg >= 10:
    print("🎉 목표 달성! (10건/초 이상)")
else:
    print("⚠️ 목표 미달 (10건/초 미만) — 배치 크기 조정 필요")

# 샘플 결과 출력
labels = ["positive", "negative", "neutral"]
for i in range(5):
    p = probs[i].numpy()
    label = labels[p.argmax()]
    score = float(p[0] - p[1])  # positive - negative
    print(f"  {label:>8} ({score:+.3f}): {headlines[i][:60]}")
PYEOF

python scripts/benchmark_finbert.py`}</Pre>

    <Chk items={[
      "Miniconda 설치 + conda activate quant-v31",
      "핵심 패키지 설치 (polars, fastapi, psycopg3, sqlalchemy)",
      "V3.1 패키지 설치 (hmmlearn, torch CPU, transformers, shap, praw)",
      "FinBERT 모델 다운로드 완료 (~420MB)",
      "verify_env.py 실행 → 전체 통과 (100%)",
      "PostgreSQL + TimescaleDB 연결 성공",
      "Redis 연결 성공",
      "HMM 3-State 동작 확인",
      "FinBERT 추론 테스트 성공",
      "FinBERT 벤치마크 10건/초 이상 확인",
    ]} />
  </div>);
}

function DotnetSetup() {
  return (<div>
    <Info c={C.blue} icon="🔷" title="Step 5: .NET 8 SDK + Blazor Server 프로젝트 생성">
      Ubuntu에서 .NET 8 SDK를 설치하고 Blazor Server 프로젝트를 생성합니다. Npgsql로 PostgreSQL에 직접 연결합니다.
    </Info>

    <Sec c={C.blue}>5-1. .NET 8 SDK 설치</Sec>
    <Pre>{`# Microsoft 패키지 저장소 추가
wget https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
rm packages-microsoft-prod.deb

# .NET 8 SDK 설치
sudo apt update
sudo apt install -y dotnet-sdk-8.0

# 확인
dotnet --version   # 8.0.xxx
dotnet --list-sdks # SDK 목록`}</Pre>

    <Sec c={C.violet}>5-2. Blazor Server 프로젝트 생성</Sec>
    <Pre>{`cd ~/quant-v31/dashboard

# Blazor Server 프로젝트 (Interactive Server)
dotnet new blazor -n QuantDashboard --interactivity Server
cd QuantDashboard

# NuGet 패키지 설치
dotnet add package Npgsql --version 8.0.6
dotnet add package Grpc.Net.Client --version 2.67.0
dotnet add package Google.Protobuf --version 3.28.3
dotnet add package Grpc.Tools --version 2.67.0

# DevExpress Blazor (라이센스 있으면)
# dotnet add package DevExpress.Blazor --version 24.1.6

# 빌드 테스트
dotnet build`}</Pre>

    <Sec c={C.cyan}>5-3. appsettings.json (PostgreSQL 연결)</Sec>
    <Pre>{`# appsettings.json 수정
cat > appsettings.json << 'JSON'
{
  "Logging": {
    "LogLevel": {
      "Default": "Information"
    }
  },
  "AllowedHosts": "*",
  "ConnectionStrings": {
    "Default": "Host=localhost;Port=5432;Database=quantdb;Username=quant;Password=QuantV31!Secure"
  },
  "GrpcUrl": "http://localhost:50051",
  "Urls": "http://0.0.0.0:5000"
}
JSON`}</Pre>

    <Sec c={C.emerald}>5-4. 실행 + 접속 테스트</Sec>
    <Pre>{`# Blazor Server 실행
dotnet run

# 출력 예시:
# info: Microsoft.Hosting.Lifetime[14]
#       Now listening on: http://0.0.0.0:5000

# ─── 접속 방법 ───
# VM 안에서: curl http://localhost:5000
# 호스트 Windows 브라우저에서: http://192.168.x.x:5000
#   (192.168.x.x = VM의 IP, 브릿지 어댑터 설정 시)
# 같은 네트워크 다른 PC/모바일에서도 접속 가능!`}</Pre>

    <Warn>
      접속이 안 되면 방화벽 확인: <code>sudo ufw status</code> 에서 5000 포트가 ALLOW인지 확인하세요.
    </Warn>

    <Chk items={[
      ".NET 8 SDK 설치 + dotnet --version 확인",
      "Blazor Server 프로젝트 생성 (QuantDashboard)",
      "Npgsql, Grpc.Net.Client 패키지 설치",
      "appsettings.json PostgreSQL 연결 설정",
      "dotnet run → http://0.0.0.0:5000 정상 실행",
      "호스트 Windows 브라우저에서 http://VM_IP:5000 접속 확인",
    ]} />
  </div>);
}

function ToolsIDE() {
  return (<div>
    <Info c={C.pink} icon="🛠️" title="Step 6: 개발 도구 + VS Code 원격 개발 + Git">
      호스트 Windows의 VS Code에서 VM에 SSH 접속하여 개발하는 환경을 구성합니다.
    </Info>

    <Sec c={C.pink}>6-1. VS Code Remote-SSH (★ 핵심 개발 도구)</Sec>
    <Pre>{`# ─── 호스트 Windows에서 ───

# 1. VS Code 설치 (이미 있으면 생략)
https://code.visualstudio.com/

# 2. 확장 설치 (VS Code 안에서)
#    Ctrl+Shift+X → 검색 → 설치:
#    • Remote - SSH (Microsoft)
#    • Remote - SSH: Editing Configuration Files
#    • Python (Microsoft)
#    • C# Dev Kit (Microsoft)
#    • Docker (Microsoft)

# 3. SSH 설정 파일 생성
# Windows: C:\\Users\\사용자\\.ssh\\config
# 내용:
Host quant-dev
    HostName 192.168.x.x    # VM의 IP
    User quant
    IdentityFile ~/.ssh/id_ed25519
    ForwardAgent yes

# 4. VS Code에서 접속
#    Ctrl+Shift+P → "Remote-SSH: Connect to Host"
#    → "quant-dev" 선택
#    → 새 VS Code 창이 열리며 VM에 연결!
#    → "폴더 열기" → /home/quant/quant-v31`}</Pre>

    <Info c={C.lime} icon="💡" title="VS Code Remote-SSH의 장점">
      • Windows에서 코드 편집 + VM에서 실행 (최고의 조합)<br />
      • 파일 탐색, 터미널, Git, 디버깅 모두 VM에 직접 연결<br />
      • Python/C# 확장이 VM의 인터프리터/SDK 자동 감지<br />
      • Ctrl+` (백틱)으로 통합 터미널 → VM 셸 바로 접속<br />
      • 포트 포워딩 자동: FastAPI(8000), Blazor(5000) 등
    </Info>

    <Sec c={C.violet}>6-2. VS Code 추천 확장 (VM 측 설치)</Sec>
    <Pre>{`# VS Code가 VM에 접속된 상태에서 아래 확장 설치
# (VM 측에 설치됨, 호스트와 별개)

# Python 개발
# • Python (Microsoft) — 자동 완성, 린팅
# • Pylance — 타입 체크
# • Black Formatter — 코드 포맷

# C# 개발
# • C# Dev Kit (Microsoft) — Blazor, .NET

# 데이터베이스
# • PostgreSQL (Chris Kolkman) — PG 쿼리 실행
# • SQLTools + SQLTools PostgreSQL — DB 탐색

# Docker
# • Docker (Microsoft) — 컨테이너 관리

# 기타
# • YAML — docker-compose, strategies.yaml
# • Git Graph — Git 히스토리 시각화
# • Thunder Client — REST API 테스트 (Postman 대체)`}</Pre>

    <Sec c={C.amber}>6-3. Git 설정</Sec>
    <Pre>{`# VM에서 Git 설정
git config --global user.name "Whoansoo"
git config --global user.email "your@email.com"
git config --global init.defaultBranch main
git config --global core.editor nano

# 프로젝트 Git 초기화
cd ~/quant-v31
git init

# .gitignore 생성
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.pyc
*.egg-info/
.eggs/
venv/
*.so

# 환경
.env
*.env.local

# 데이터 (대용량)
data/parquet/
models/
*.pkl
*.parquet

# IDE
.vscode/
.idea/
*.swp

# Docker
pg_data/
redis_data/

# .NET
dashboard/QuantDashboard/bin/
dashboard/QuantDashboard/obj/

# OS
.DS_Store
Thumbs.db
EOF

git add .
git commit -m "Initial: V3.1 project structure"`}</Pre>

    <Sec c={C.cyan}>6-4. .env 파일 (비밀 키 관리)</Sec>
    <Pre>{`# ~/quant-v31/.env (★ .gitignore에 포함!)
cat > ~/quant-v31/.env << 'EOF'
# ─── PostgreSQL ───
PG_PASSWORD=QuantV31!Secure
PG_DSN=postgresql+psycopg://quant:QuantV31!Secure@localhost:5432/quantdb

# ─── Redis ───
REDIS_URL=redis://localhost:6379

# ─── Alpaca (Paper Trading) ───
ALPACA_KEY=your_alpaca_key_here
ALPACA_SECRET=your_alpaca_secret_here

# ─── Anthropic (Claude API) ───
ANTHROPIC_KEY=your_anthropic_key_here

# ─── Reddit (WSB 수집) ───
REDDIT_CLIENT_ID=your_reddit_id
REDDIT_CLIENT_SECRET=your_reddit_secret

# ─── Telegram (알림) ───
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# ─── FRED (매크로) ───
FRED_API_KEY=your_fred_key
EOF

chmod 600 .env  # 소유자만 읽기`}</Pre>

    <Sec c={C.emerald}>6-5. 일상 개발 워크플로우</Sec>
    <Pre>{`# ─── 매일 개발 시작 루틴 ───

# 1. VM 시작 (VirtualBox)
#    → 또는 VBoxManage startvm quant-v31-dev --type headless

# 2. VS Code → Remote-SSH → quant-dev 접속

# 3. 통합 터미널 (Ctrl+\`)에서:
cdq                           # ~/quant-v31로 이동
docker compose up -d          # PG + Redis 시작
conda activate quant-v31      # Python 환경

# 4. tmux 세션 (여러 작업 병렬)
tmux new -s dev
# Ctrl+b | → 세로 분할
# 왼쪽: 코드 실행
# 오른쪽: docker logs 모니터

# 5. 작업 종료
# Ctrl+b d → tmux 세션 분리 (백그라운드 유지)
# SSH 끊어도 작업 계속 실행됨!

# ─── 유용한 명령어 ───
dps                           # Docker 컨테이너 상태
dlogs                         # Docker 로그 실시간
pg                            # PostgreSQL 접속
redis-cli                     # Redis 접속

# Python 스크립트 실행
python scripts/verify_env.py           # 환경 검증
python scripts/benchmark_finbert.py    # FinBERT 벤치마크

# Blazor 실행 (별도 터미널)
cd dashboard/QuantDashboard && dotnet run`}</Pre>

    <Chk items={[
      "VS Code + Remote-SSH 확장 설치 (호스트 Windows)",
      "SSH config에 quant-dev 호스트 등록",
      "VS Code에서 VM 원격 접속 성공",
      "Python, C# Dev Kit 등 VM측 확장 설치",
      "Git 초기화 + .gitignore 설정",
      ".env 파일 생성 (API 키 등)",
      "tmux 세션 사용법 숙지",
    ]} />
  </div>);
}

function FinalCheck() {
  return (<div>
    <Info c={C.emerald} icon="✅" title="Step 7: 최종 검증 + 트러블슈팅">
      전체 환경이 정상인지 최종 확인하고, 자주 발생하는 문제와 해결법을 정리합니다.
    </Info>

    <Sec c={C.emerald}>7-1. 전체 환경 최종 검증</Sec>
    <Pre>{`# 한 번에 전체 확인하는 원라이너
echo "=== System ===" && \\
echo "OS: $(lsb_release -ds)" && \\
echo "RAM: $(free -h | awk '/Mem/{print $2}')" && \\
echo "Disk: $(df -h / | awk 'NR==2{print $4}') free" && \\
echo "CPU: $(nproc) cores" && \\
echo "" && \\
echo "=== Docker ===" && \\
docker --version && \\
docker compose version && \\
echo "Containers: $(docker ps -q | wc -l) running" && \\
echo "" && \\
echo "=== PostgreSQL ===" && \\
docker exec quant-postgres psql -U quant -d quantdb -t -c \\
  "SELECT 'PG ' || version()::text" 2>/dev/null | head -1 && \\
docker exec quant-postgres psql -U quant -d quantdb -t -c \\
  "SELECT 'TimescaleDB ' || extversion FROM pg_extension WHERE extname='timescaledb'" 2>/dev/null && \\
docker exec quant-postgres psql -U quant -d quantdb -t -c \\
  "SELECT 'Hypertables: ' || count(*)::text FROM timescaledb_information.hypertables" 2>/dev/null && \\
echo "" && \\
echo "=== Redis ===" && \\
docker exec quant-redis redis-cli ping && \\
echo "" && \\
echo "=== Python ===" && \\
conda activate quant-v31 2>/dev/null && \\
python --version && \\
python -c "import psycopg; print('psycopg3 OK')" && \\
python -c "from hmmlearn.hmm import GaussianHMM; print('HMM OK')" && \\
python -c "import torch; print(f'PyTorch {torch.__version__} CPU')" && \\
python -c "import transformers; print(f'Transformers {transformers.__version__}')" && \\
echo "" && \\
echo "=== .NET ===" && \\
dotnet --version && \\
echo "" && \\
echo "🎉 All checks complete!"`}</Pre>

    <Sec c={C.amber}>7-2. 자주 발생하는 문제 + 해결</Sec>
    {[
      { q: "docker compose up 시 postgres 컨테이너가 계속 재시작",
        a: "shared_buffers가 VM 메모리보다 큰 경우 발생. docker-compose.yml에서 shared_buffers를 6GB로 줄이거나, shm_size를 2g으로 확인.",
        cmd: "docker logs quant-postgres  # 에러 로그 확인" },
      { q: "호스트 브라우저에서 VM의 Blazor(5000)에 접속 안 됨",
        a: "1) VirtualBox 네트워크가 '브릿지 어댑터'인지 확인 (NAT이면 포트포워딩 필요)\n2) UFW: sudo ufw allow 5000\n3) Blazor가 0.0.0.0:5000으로 리슨하는지 확인 (localhost만이면 외부 접속 불가)",
        cmd: 'dotnet run --urls "http://0.0.0.0:5000"' },
      { q: "psycopg.OperationalError: connection refused",
        a: "Docker 컨테이너가 아직 시작 안 됨. docker compose up -d 후 10초 대기.\n또는 pg_isready로 확인.",
        cmd: "docker exec quant-postgres pg_isready -U quant" },
      { q: "FinBERT 다운로드 실패 / timeout",
        a: "네트워크 문제. VM의 DNS 확인 후 재시도.",
        cmd: "cat /etc/resolv.conf  # DNS 확인\nsudo systemd-resolve --flush-caches" },
      { q: "VM이 느림 / 멈춤",
        a: "1) VT-x/AMD-V 중첩 활성화 확인\n2) Hyper-V가 호스트에서 비활성화인지 확인\n3) VM 메모리를 24GB로 줄여보기\n4) Host I/O 캐시 활성화 확인",
        cmd: "htop  # VM 리소스 사용량 확인" },
      { q: "Docker 이미지 pull 속도가 느림",
        a: "Docker Hub 미러 설정. /etc/docker/daemon.json에 미러 추가.",
        cmd: 'echo \'{"registry-mirrors":["https://mirror.gcr.io"]}\' | sudo tee /etc/docker/daemon.json\nsudo systemctl restart docker' },
    ].map((item, i) => (
      <div key={i} style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 8,
        padding: "10px 14px", margin: "8px 0" }}>
        <div style={{ color: C.rose, fontWeight: 700, fontSize: 12, marginBottom: 4 }}>
          Q: {item.q}
        </div>
        <div style={{ color: C.t, fontSize: 11, lineHeight: 1.6, marginBottom: 6 }}>
          A: {item.a}
        </div>
        <pre style={{ color: C.cyan, fontSize: 9.5, background: "#04050a", padding: "6px 10px",
          borderRadius: 6, margin: 0, whiteSpace: "pre-wrap" }}>{item.cmd}</pre>
      </div>
    ))}

    <Sec c={C.lime}>7-3. 개발 → 운영 전환 경로</Sec>
    <Info c={C.lime} icon="🚀" title="VirtualBox → Dell 서버 베어메탈 전환">
      Phase 1~3을 VirtualBox에서 개발 완료 후, Phase 4(Paper Trading)부터는 Dell 서버에 Ubuntu를 직접 설치하여 24/7 운용합니다.<br /><br />
      <b>전환 방법 (매우 간단):</b><br />
      1. Dell 서버에 Ubuntu 24.04 LTS 설치<br />
      2. Docker + .NET 8 + conda 설치 (이 가이드 Step 2~5 반복)<br />
      3. <code>git clone</code>으로 코드 복사<br />
      4. <code>docker compose up -d</code><br />
      5. conda 환경 재구축 + FinBERT 다운로드<br />
      6. 끝! 동일하게 동작합니다.
    </Info>

    <Sec c={C.violet}>전체 설치 소요 시간 예상</Sec>
    <Stat items={[
      { c: C.blue, label: "Step 1 VBox+Ubuntu", value: "~1시간", sub: "설치+부팅" },
      { c: C.cyan, label: "Step 2 기본설정", value: "~30분", sub: "패키지+SSH" },
      { c: C.orange, label: "Step 3 Docker+DB", value: "~30분", sub: "이미지 다운로드" },
      { c: C.violet, label: "Step 4 Python", value: "~1시간", sub: "FinBERT 420MB" },
    ]} />
    <Stat items={[
      { c: C.blue, label: "Step 5 .NET", value: "~20분", sub: "SDK+프로젝트" },
      { c: C.pink, label: "Step 6 도구", value: "~20분", sub: "VS Code 설정" },
      { c: C.emerald, label: "Step 7 검증", value: "~10분", sub: "테스트 실행" },
    ]} />
    <div style={{ textAlign: "center", margin: "12px 0", color: C.tw, fontSize: 14, fontWeight: 800 }}>
      총 예상 시간: <span style={{ color: C.emerald }}>약 3~4시간</span>
    </div>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════
const tabs = [
  { id: "vbox", icon: "📦", label: "VBox+Ubuntu", c: C.blue },
  { id: "base", icon: "🐧", label: "기본 설정", c: C.cyan },
  { id: "docker", icon: "🐳", label: "Docker+DB", c: C.orange },
  { id: "python", icon: "🐍", label: "Python", c: C.violet },
  { id: "dotnet", icon: "🔷", label: ".NET 8", c: C.blue },
  { id: "tools", icon: "🛠️", label: "개발 도구", c: C.pink },
  { id: "final", icon: "✅", label: "최종 검증", c: C.emerald },
];
const pages = {
  vbox: VBoxSetup, base: UbuntuBase, docker: DockerSetup,
  python: PythonSetup, dotnet: DotnetSetup, tools: ToolsIDE, final: FinalCheck,
};

export default function App() {
  const [active, setActive] = useState("vbox");
  const Page = pages[active];
  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.t,
      fontFamily: "'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" }}>
      <link href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css" rel="stylesheet" />
      <div style={{ background: "linear-gradient(180deg,#0d0e1a,#05060b)",
        borderBottom: `1px solid ${C.bd}`, padding: "16px 16px 10px", textAlign: "center" }}>
        <div style={{ display: "flex", justifyContent: "center", gap: 6, marginBottom: 6 }}>
          <span style={{ background: `${C.orange}15`, color: C.orange, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.orange}30` }}>V3.1</span>
          <span style={{ background: `${C.cyan}15`, color: C.cyan, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.cyan}30` }}>DEV ENV</span>
        </div>
        <h1 style={{ fontSize: 18, fontWeight: 900, margin: "2px 0",
          background: "linear-gradient(135deg,#3b82f6,#06b6d4,#10b981,#8b5cf6)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          Ubuntu VM 개발환경 구축 가이드
        </h1>
        <p style={{ color: C.tm, fontSize: 10, margin: 0 }}>
          VirtualBox + Ubuntu 24.04 + Docker + PostgreSQL/TimescaleDB + Python + .NET 8 + VS Code
        </p>
      </div>

      <div style={{ display: "flex", overflowX: "auto", gap: 2, padding: "6px 8px",
        borderBottom: `1px solid ${C.bd}`, background: "#080a12" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActive(t.id)}
            style={{
              background: active === t.id ? `${t.c}15` : "transparent",
              border: active === t.id ? `1px solid ${t.c}30` : "1px solid transparent",
              borderRadius: 7, padding: "5px 9px", cursor: "pointer",
              color: active === t.id ? t.c : C.tm,
              fontSize: 11, fontWeight: active === t.id ? 700 : 500,
              whiteSpace: "nowrap", fontFamily: "inherit",
            }}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      <div style={{ padding: "10px 12px", maxWidth: 880, margin: "0 auto" }}>
        <Page />
      </div>

      <div style={{ textAlign: "center", padding: "14px", borderTop: `1px solid ${C.bd}`,
        color: "#333846", fontSize: 9 }}>
        Quant V3.1 Dev Environment Guide | Windows 10 (64GB) → VirtualBox → Ubuntu 24.04
      </div>
    </div>
  );
}
