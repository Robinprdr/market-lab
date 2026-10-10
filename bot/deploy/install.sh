#!/usr/bin/env bash
set -euo pipefail
# Run on an already-authorized Ubuntu 24.04 server; provisions nothing in OCI.
[[ "$(id -u)" == 0 ]] || { echo 'Run with sudo on the target Ubuntu server'; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Ubuntu 24.04 required'; exit 1; }
case "$(uname -m)" in aarch64|x86_64) ;; *) echo 'Unsupported architecture'; exit 1;; esac
[[ -f /opt/market-lab/requirements-cloud.txt ]] || { echo 'Extract deployment bundle into /opt first'; exit 1; }
apt-get update
apt-get install -y python3-venv python3-dev build-essential curl ca-certificates xvfb x11vnc libxtst6 libxi6 libxrender1 libgtk-3-0t64 ufw
id marketlab >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/market-lab --shell /bin/bash marketlab
install -d -o marketlab -g marketlab -m 0700 /var/lib/market-lab /var/lib/market-lab/backups
install -d -o root -g marketlab -m 0750 /etc/market-lab
if [[ ! -f /etc/market-lab/cloud.env ]]; then install -o root -g marketlab -m 0640 /opt/market-lab/bot/deploy/cloud.env.example /etc/market-lab/cloud.env; fi
chown -R root:marketlab /opt/market-lab
chmod -R g-w,o-rwx /opt/market-lab
python3 -m venv /opt/market-lab/.venv
/opt/market-lab/.venv/bin/pip install -r /opt/market-lab/requirements-cloud.txt
install -m 0755 /opt/market-lab/bot/deploy/start-gateway /opt/market-lab/bot/deploy/start-gateway.launcher
install -m 0644 /opt/market-lab/bot/deploy/systemd/* /etc/systemd/system/
install -d /etc/systemd/journald.conf.d
install -m 0644 /opt/market-lab/bot/deploy/journald.conf /etc/systemd/journald.conf.d/market-lab.conf
systemctl daemon-reload
cd /opt/market-lab
# No service enabled/started here: the user inspects configuration first.
echo 'Installed. Services STOPPED; no broker connection or orders. Read bot/DEPLOY_ORACLE.md.'
