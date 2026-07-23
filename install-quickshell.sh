#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
qs_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/quickshell"
toggle_file="${qs_dir}/panel/ToggleGrid.qml"
component_file="${qs_dir}/panel/NightLightSync.qml"
config_file="${XDG_CONFIG_HOME:-${HOME}/.config}/hyprsunset-sync/config.env"

if [[ ! -f "${toggle_file}" ]]; then
    echo "Quickshell toggle grid not found: ${toggle_file}" >&2
    exit 1
fi

bash "${project_dir}/install.sh"
install -Dm644 "${project_dir}/quickshell/NightLightSync.qml" "${component_file}"

if ! grep -q 'NightLightSync { id: nightLight }' "${toggle_file}"; then
    patch \
        --directory="${qs_dir}" \
        --strip=1 \
        --backup \
        --suffix=.pre-hyprsunset-sync \
        <"${project_dir}/quickshell/ToggleGrid.qml.patch"
fi

# Preserve the temperature used by the panel before it was integrated.
sed -i 's/^TEMPERATURE=.*/TEMPERATURE=3500/' "${config_file}"
systemctl --user restart hyprsunset-sync.service

echo "Quickshell Night Light integration installed."
echo "Backup: ${toggle_file}.pre-hyprsunset-sync"
echo "Reload with: ${qs_dir}/scripts/launch.sh"
