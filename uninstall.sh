#!/usr/bin/env bash
set -euo pipefail

config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"

systemctl --user disable --now hyprsunset-sync.service 2>/dev/null || true
rm -f \
    "${HOME}/.local/bin/hyprsunset-sync" \
    "${config_home}/systemd/user/hyprsunset-sync.service"
systemctl --user daemon-reload

echo "Listener removed."
echo "Configuration was retained at ${config_home}/hyprsunset-sync/config.env"
