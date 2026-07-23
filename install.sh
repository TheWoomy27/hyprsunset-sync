#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${HOME}/.local/bin"
config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/hyprsunset-sync"
unit_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
config_file="${config_dir}/config.env"
start_service=true

if [[ "${1:-}" == "--no-start" ]]; then
    start_service=false
elif [[ $# -gt 0 ]]; then
    echo "Usage: $0 [--no-start]" >&2
    exit 2
fi

for command in python3 hyprctl hyprsunset systemctl; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "Missing required command: ${command}" >&2
        exit 1
    fi
done

install -Dm755 "${project_dir}/src/hyprsunset_sync.py" "${bin_dir}/hyprsunset-sync"
install -Dm644 \
    "${project_dir}/systemd/hyprsunset-sync.service" \
    "${unit_dir}/hyprsunset-sync.service"

if [[ ! -e "${config_file}" ]]; then
    install -d -m700 "${config_dir}"
    topic="hyprsunset-sync-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    {
        echo "# Treat NTFY_TOPIC as a password. Do not publish it."
        echo "NTFY_BASE_URL=https://ntfy.sh"
        echo "NTFY_TOPIC=${topic}"
        echo "TEMPERATURE=4500"
        echo "OFF_ACTION=identity"
        echo "# NTFY_TOKEN=tk_example  # Optional, for an authenticated/self-hosted topic"
    } >"${config_file}"
    chmod 600 "${config_file}"
    echo "Created ${config_file}"
else
    echo "Preserved existing ${config_file}"
fi

if [[ "${start_service}" == true ]]; then
    systemctl --user daemon-reload
    systemctl --user enable hyprsunset-sync.service
    systemctl --user restart hyprsunset-sync.service
fi

topic="$(sed -n 's/^NTFY_TOPIC=//p' "${config_file}" | head -n1)"
base_url="$(sed -n 's/^NTFY_BASE_URL=//p' "${config_file}" | head -n1)"

echo
if [[ "${start_service}" == true ]]; then
    echo "PC listener installed and started."
else
    echo "PC listener installed without starting the service."
fi
echo "Tasker publish URL: ${base_url%/}/${topic}"
echo "On body:  on"
echo "Off body: off"
echo
echo "Verify with:"
echo "  systemctl --user status hyprsunset-sync.service"
echo "  journalctl --user -u hyprsunset-sync.service -f"
