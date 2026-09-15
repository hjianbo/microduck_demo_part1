#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
command -v uuidgen >/dev/null || { echo "uuidgen is required" >&2; exit 1; }

git submodule update --init --recursive

mkdir -p .demo
if [[ ! -f .demo/session.env ]]; then
    session_id="$(uuidgen | tr '[:upper:]' '[:lower:]' | tr -d '-')"
    umask 077
    {
        echo "MICRODUCK_SESSION_ID=${session_id}"
        echo "MICRODUCK_BROKER_HOST=broker.emqx.io"
        echo "MICRODUCK_BROKER_PORT=1883"
        echo "MICRODUCK_TOPIC_PREFIX=microduck/demo"
        echo "MICRODUCK_COMMAND_TIMEOUT=1.0"
    } > .demo/session.env
    echo "Created private demo session: ${session_id}"
else
    echo "Keeping existing private demo session"
fi

session_id="$(sed -n 's/^MICRODUCK_SESSION_ID=//p' .demo/session.env)"
if [[ ! -f .demo/device-agent.env ]]; then
    umask 077
    {
        echo "# Replace these values with the product and device created in Device Agent."
        echo "DEVICE_AGENT_BROKER=mqtt://broker.emqx.io:1883"
        echo "DEVICE_AGENT_PRODUCT_ID=microduck-demo"
        echo "DEVICE_AGENT_DEVICE_ID=microduck-${session_id}"
        echo "DEVICE_AGENT_USERNAME="
        echo "DEVICE_AGENT_PASSWORD="
        echo "DEVICE_AGENT_MQTT_QOS=1"
        echo "DEVICE_AGENT_MQTT_KEEPALIVE=30"
        echo "DEVICE_AGENT_COMMAND_TIMEOUT=1.0"
    } > .demo/device-agent.env
    echo "Created local MQTT config: .demo/device-agent.env"
else
    echo "Keeping existing Device Agent MQTT config"
fi

uv sync --locked
uv sync --project vendor/microduck_rl --locked
vendor/microduck_rl/.venv/bin/python scripts/fetch_policy.py
uv pip install --python vendor/microduck_rl/.venv/bin/python --editable .
vendor/microduck_rl/.venv/bin/python scripts/build_runner.py
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.runner_builder

export MICRODUCK_MQTT_CONFIG="$project_root/.demo/session.env"
vendor/microduck_rl/.venv/bin/microduck-session
echo
echo "Setup complete. Next:"
echo "  Terminal 1: ./scripts/run_device_agent_integration_demo.sh"
echo "  Terminal 2: vendor/microduck_rl/.venv/bin/microduck-device-demo move forward --duration 5"
