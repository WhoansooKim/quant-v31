#!/bin/bash
# ═══════════════════════════════════════
# Quant V3.1 — systemd Service Manager
# ═══════════════════════════════════════
set -e

SERVICES=("quant-engine" "quant-dashboard")
ALL_SERVICES=("quant-engine" "quant-dashboard" "quant-scheduler")
SYSTEMD_DIR="/etc/systemd/system"
PROJECT_DIR="/home/quant/quant-v31"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs|enable|disable}"
    echo ""
    echo "Commands:"
    echo "  install     Copy service files + daemon-reload + enable"
    echo "  uninstall   Stop + disable + remove service files"
    echo "  start       Start engine + dashboard"
    echo "  stop        Stop all services"
    echo "  restart     Restart engine + dashboard"
    echo "  status      Show service status"
    echo "  logs [svc]  Show logs (default: engine)"
    echo "  enable      Enable auto-start on boot"
    echo "  disable     Disable auto-start on boot"
    echo "  build       Build dashboard before starting"
    echo ""
    echo "Services: ${SERVICES[*]}"
    echo "Optional: quant-scheduler (standalone mode)"
    exit 1
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}This command requires sudo${NC}"
        exit 1
    fi
}

cmd_install() {
    check_root
    echo -e "${YELLOW}Installing Quant V3.1 services...${NC}"

    # Copy service files
    for svc in "${ALL_SERVICES[@]}"; do
        cp "${PROJECT_DIR}/systemd/${svc}.service" "${SYSTEMD_DIR}/"
        echo -e "  ${GREEN}Copied${NC} ${svc}.service"
    done

    # Reload systemd
    systemctl daemon-reload
    echo -e "  ${GREEN}daemon-reload OK${NC}"

    # Enable core services (not standalone scheduler)
    for svc in "${SERVICES[@]}"; do
        systemctl enable "$svc"
        echo -e "  ${GREEN}Enabled${NC} $svc"
    done

    echo -e "\n${GREEN}Installation complete.${NC}"
    echo "  Run: sudo $0 start"
    echo "  (Optional) Enable standalone scheduler: sudo systemctl enable quant-scheduler"
}

cmd_uninstall() {
    check_root
    echo -e "${YELLOW}Uninstalling Quant V3.1 services...${NC}"

    for svc in "${ALL_SERVICES[@]}"; do
        systemctl stop "$svc" 2>/dev/null || true
        systemctl disable "$svc" 2>/dev/null || true
        rm -f "${SYSTEMD_DIR}/${svc}.service"
        echo -e "  ${GREEN}Removed${NC} $svc"
    done

    systemctl daemon-reload
    echo -e "${GREEN}Uninstall complete.${NC}"
}

cmd_start() {
    echo -e "${YELLOW}Starting Quant V3.1...${NC}"
    for svc in "${SERVICES[@]}"; do
        sudo systemctl start "$svc"
        echo -e "  ${GREEN}Started${NC} $svc"
    done
    sleep 2
    cmd_status
}

cmd_stop() {
    echo -e "${YELLOW}Stopping Quant V3.1...${NC}"
    for svc in "${ALL_SERVICES[@]}"; do
        sudo systemctl stop "$svc" 2>/dev/null || true
        echo -e "  ${GREEN}Stopped${NC} $svc"
    done
}

cmd_restart() {
    echo -e "${YELLOW}Restarting Quant V3.1...${NC}"
    for svc in "${SERVICES[@]}"; do
        sudo systemctl restart "$svc"
        echo -e "  ${GREEN}Restarted${NC} $svc"
    done
    sleep 2
    cmd_status
}

cmd_status() {
    echo -e "${YELLOW}━━━ Quant V3.1 Service Status ━━━${NC}"
    for svc in "${ALL_SERVICES[@]}"; do
        state=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
        enabled=$(systemctl is-enabled "$svc" 2>/dev/null || echo "disabled")
        if [[ "$state" == "active" ]]; then
            echo -e "  ${GREEN}●${NC} ${svc}: ${GREEN}${state}${NC} (${enabled})"
        else
            echo -e "  ${RED}●${NC} ${svc}: ${RED}${state}${NC} (${enabled})"
        fi
    done

    echo ""
    echo -e "${YELLOW}━━━ Port Status ━━━${NC}"
    for port_info in "8000:Engine(FastAPI)" "50051:gRPC" "5000:Dashboard(Blazor)"; do
        port="${port_info%%:*}"
        name="${port_info#*:}"
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            echo -e "  ${GREEN}●${NC} :${port} ${name} — listening"
        else
            echo -e "  ${RED}●${NC} :${port} ${name} — not listening"
        fi
    done

    echo ""
    echo -e "${YELLOW}━━━ Docker (PG + Redis) ━━━${NC}"
    for container in "timescaledb" "redis"; do
        state=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || echo "not found")
        if [[ "$state" == "running" ]]; then
            echo -e "  ${GREEN}●${NC} ${container}: ${GREEN}running${NC}"
        else
            echo -e "  ${RED}●${NC} ${container}: ${RED}${state}${NC}"
        fi
    done
}

cmd_logs() {
    local svc="${1:-quant-engine}"
    echo -e "${YELLOW}Showing logs for ${svc}...${NC}"
    journalctl -u "$svc" -f --no-pager -n 50
}

cmd_enable() {
    for svc in "${SERVICES[@]}"; do
        sudo systemctl enable "$svc"
        echo -e "  ${GREEN}Enabled${NC} $svc"
    done
}

cmd_disable() {
    for svc in "${SERVICES[@]}"; do
        sudo systemctl disable "$svc"
        echo -e "  ${GREEN}Disabled${NC} $svc"
    done
}

cmd_build() {
    echo -e "${YELLOW}Building dashboard...${NC}"
    cd "${PROJECT_DIR}/dashboard/QuantDashboard"
    dotnet build -c Release 2>&1
    echo -e "${GREEN}Build complete.${NC}"
}

# ─── Main ───
case "${1:-}" in
    install)    cmd_install ;;
    uninstall)  cmd_uninstall ;;
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    status)     cmd_status ;;
    logs)       cmd_logs "$2" ;;
    enable)     cmd_enable ;;
    disable)    cmd_disable ;;
    build)      cmd_build ;;
    *)          usage ;;
esac
