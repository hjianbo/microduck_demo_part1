#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runner="$project_root/.generated/device_agent_integration_demo/infer_policy.py"
default_mqtt_config="$project_root/.demo/device-agent.env"
walking="$project_root/.demo/models/BEST_alpha_walking.onnx"
kick_left="$project_root/vendor/microduck_simulator/app/public/policies/ball_kick_left.onnx"
kick_right="$project_root/vendor/microduck_simulator/app/public/policies/ball_kick_right.onnx"

[[ -f "$runner" && -f "$walking" ]] || {
    echo "Demo is not initialized. Run ./scripts/bootstrap.sh first." >&2
    exit 1
}
[[ -f "$kick_left" && -f "$kick_right" ]] || {
    echo "Kick policies are missing from vendor/microduck_simulator." >&2
    exit 1
}

if [[ -z "${DEVICE_AGENT_MQTT_CONFIG:-}" ]]; then
    export DEVICE_AGENT_MQTT_CONFIG="$default_mqtt_config"
fi
[[ -f "$DEVICE_AGENT_MQTT_CONFIG" ]] || {
    echo "MQTT config is missing: $DEVICE_AGENT_MQTT_CONFIG" >&2
    echo "Run ./scripts/bootstrap.sh or point DEVICE_AGENT_MQTT_CONFIG at your config file." >&2
    exit 1
}

cd "$project_root/vendor/microduck_rl"
python_bin="$project_root/vendor/microduck_rl/.venv/bin/python"
runtime_bin="$python_bin"
if [[ "$(uname -s)" == "Darwin" ]]; then
    runtime_bin="$project_root/vendor/microduck_rl/.venv/bin/mjpython"
    python_base="$($python_bin -c 'import sys; print(sys.base_prefix)')"
    export DYLD_LIBRARY_PATH="$python_base/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

exec "$runtime_bin" "$runner" \
    --walking "$walking" \
    --kick-left "$kick_left" \
    --kick-right "$kick_right" \
    --kick-duration 0.5 \
    --new-cmd-obs "$@"
