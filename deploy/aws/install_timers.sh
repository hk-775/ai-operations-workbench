#!/bin/bash
# Run as root after both workspaces start; jobs themselves use the host account.
set -euo pipefail
install -d -m 700 -o workbench -g workbench /opt/workbench/docker-client
if [ ! -e /opt/workbench/docker-client/config.json ]; then
  printf '{}\n' > /opt/workbench/docker-client/config.json
  chown workbench:workbench /opt/workbench/docker-client/config.json
  chmod 600 /opt/workbench/docker-client/config.json
fi
for operation in backup metrics; do
  cat > "/etc/systemd/system/workbench-${operation}.service" <<EOF
[Unit]
Description=Workbench hosted test ${operation}
After=network-online.target docker.service
Wants=network-online.target
[Service]
Type=oneshot
User=workbench
Group=workbench
UMask=0077
Environment=HOME=/home/workbench
Environment=DOCKER_CONFIG=/opt/workbench/docker-client
ExecStart=/usr/bin/python3 /opt/workbench/demo/deploy/aws/host_operations.py ${operation}
TimeoutStartSec=15min
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
EOF
done
cat > /etc/systemd/system/workbench-backup.timer <<'EOF'
[Unit]
Description=Daily Workbench off-host backup, including a scheduled initial run
[Timer]
OnActiveSec=30s
OnCalendar=*-*-* 03:00:00 UTC
Persistent=true
RandomizedDelaySec=10s
[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/workbench-metrics.timer <<'EOF'
[Unit]
Description=Minute Workbench service and backup freshness check
[Timer]
OnActiveSec=10s
OnUnitActiveSec=60s
AccuracySec=1s
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now workbench-backup.timer workbench-metrics.timer
# Apply changed schedules too; the initial backup is genuinely timer-triggered.
systemctl restart workbench-backup.timer workbench-metrics.timer
