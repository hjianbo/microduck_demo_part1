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

uv sync --project vendor/microduck_rl --locked
vendor/microduck_rl/.venv/bin/python scripts/fetch_policy.py
uv pip install --python vendor/microduck_rl/.venv/bin/python --editable .
vendor/microduck_rl/.venv/bin/python scripts/build_runner.py

export MICRODUCK_MQTT_CONFIG="$project_root/.demo/session.env"
vendor/microduck_rl/.venv/bin/microduck-session
echo
echo "Setup complete. Next:"
echo "  Terminal 1: ./scripts/run_simulator.sh"
echo "  Terminal 2: ./scripts/send.sh forward --duration 3"
