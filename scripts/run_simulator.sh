#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="$project_root/.demo/session.env"
runner="$project_root/.generated/mqtt_infer_policy.py"
policy="$project_root/.demo/models/BEST_alpha_walking.onnx"

[[ -f "$config" && -f "$runner" ]] || {
    echo "Demo is not initialized. Run ./scripts/bootstrap.sh first." >&2
    exit 1
}
[[ -f "$policy" ]] || { echo "Walking policy not found: $policy" >&2; exit 1; }

export MICRODUCK_MQTT_CONFIG="$config"
cd "$project_root/vendor/microduck_rl"

python_bin="$project_root/vendor/microduck_rl/.venv/bin/python"
runtime_bin="$python_bin"
if [[ "$(uname -s)" == "Darwin" ]]; then
    runtime_bin="$project_root/vendor/microduck_rl/.venv/bin/mjpython"
    python_base="$($python_bin -c 'import sys; print(sys.base_prefix)')"
    export DYLD_LIBRARY_PATH="$python_base/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

exec "$runtime_bin" "$runner" \
    --walking "$policy" \
    --new-cmd-obs "$@"
