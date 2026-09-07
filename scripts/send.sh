#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="$project_root/.demo/session.env"
[[ -f "$config" ]] || {
    echo "Demo is not initialized. Run ./scripts/bootstrap.sh first." >&2
    exit 1
}

export MICRODUCK_MQTT_CONFIG="$config"
cd "$project_root"
exec "$project_root/vendor/microduck_rl/.venv/bin/microduck-send" "$@"
