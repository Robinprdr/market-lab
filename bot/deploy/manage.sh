#!/usr/bin/env bash
set -euo pipefail
[[ "$(id -u)" == 0 ]] || { echo 'Run with sudo on the server'; exit 1; }
case "${1:-}" in
 start) systemctl enable --now market-lab-scheduler.service market-lab-dashboard.service market-lab-health.timer market-lab-backup.timer ;;
 telegram) systemctl enable --now market-lab-telegram.service ;;
 stop) systemctl stop market-lab-scheduler.service market-lab-dashboard.service market-lab-telegram.service market-lab-health.timer market-lab-backup.timer ;;
 status) systemctl --no-pager status market-lab-scheduler.service market-lab-dashboard.service market-lab-telegram.service market-lab-health.timer market-lab-backup.timer ;;
 *) echo 'Usage: sudo bash bot/deploy/manage.sh start|telegram|stop|status'; exit 1 ;;
esac
