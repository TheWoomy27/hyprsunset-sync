#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
qs_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/quickshell"
toggle_file="${qs_dir}/panel/ToggleGrid.qml"
component_dir=""
auto_patch=false
no_start=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto-patch)
            auto_patch=true
            shift
            ;;
        --component-dir)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "--component-dir requires a path" >&2
                exit 2
            fi
            component_dir="$2"
            shift 2
            ;;
        --no-start)
            no_start=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--component-dir PATH] [--auto-patch] [--no-start]"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

if [[ ! -d "${qs_dir}" ]]; then
    echo "Quickshell configuration directory not found: ${qs_dir}" >&2
    echo "The core listener does not require Quickshell; run ./install.sh instead." >&2
    exit 1
fi

if [[ -z "${component_dir}" ]]; then
    if [[ "${auto_patch}" == true ]]; then
        component_dir="${qs_dir}/panel"
    else
        component_dir="${qs_dir}"
    fi
fi

needs_patch=false
if [[ "${auto_patch}" == true ]]; then
    if [[ "${component_dir}" != "${qs_dir}/panel" ]]; then
        echo "--auto-patch requires the component in ${qs_dir}/panel" >&2
        exit 2
    fi
    if [[ ! -f "${toggle_file}" ]]; then
        echo "Auto-patch target not found: ${toggle_file}" >&2
        exit 1
    fi
    if ! grep -q 'NightLightSync { id: nightLight }' "${toggle_file}"; then
        if ! patch \
            --dry-run \
            --batch \
            --forward \
            --directory="${qs_dir}" \
            --strip=1 \
            <"${project_dir}/quickshell/patches/ToggleGrid.qml.patch"
        then
            echo "ToggleGrid.qml does not match the optional patch." >&2
            echo "No panel files were changed; use the generic guide instead." >&2
            exit 1
        fi
        needs_patch=true
    fi
fi

install_args=()
if [[ "${no_start}" == true ]]; then
    install_args+=(--no-start)
fi
bash "${project_dir}/install.sh" "${install_args[@]}"
install -Dm644 \
    "${project_dir}/quickshell/NightLightSync.qml" \
    "${component_dir}/NightLightSync.qml"

if [[ "${needs_patch}" == true ]]; then
    patch \
        --batch \
        --forward \
        --directory="${qs_dir}" \
        --strip=1 \
        --backup \
        --suffix=.pre-hyprsunset-sync \
        <"${project_dir}/quickshell/patches/ToggleGrid.qml.patch"
fi

echo
echo "Installed reusable Quickshell controller:"
echo "  ${component_dir}/NightLightSync.qml"
if [[ "${auto_patch}" == true ]]; then
    echo "Integrated compatible panel toggle:"
    echo "  ${toggle_file}"
    echo "Backup (when patched):"
    echo "  ${toggle_file}.pre-hyprsunset-sync"
else
    echo "No panel files were modified."
    echo "See docs/quickshell.md for the two-line binding API."
fi
