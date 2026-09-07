from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class DemoConfig:
    broker_host: str
    broker_port: int
    session_id: str
    topic: str
    command_timeout: float


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid config line {line_number} in {path}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_config(path: str | Path | None = None) -> DemoConfig:
    configured_path = path or os.environ.get("MICRODUCK_MQTT_CONFIG")
    if not configured_path:
        raise RuntimeError(
            "MICRODUCK_MQTT_CONFIG is not set. Run ./scripts/bootstrap.sh first."
        )

    config_path = Path(configured_path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Demo config not found: {config_path}")

    values = _parse_env_file(config_path)
    session_id = values["MICRODUCK_SESSION_ID"]
    topic_prefix = values.get("MICRODUCK_TOPIC_PREFIX", "microduck/demo").strip("/")
    return DemoConfig(
        broker_host=values.get("MICRODUCK_BROKER_HOST", "broker.emqx.io"),
        broker_port=int(values.get("MICRODUCK_BROKER_PORT", "1883")),
        session_id=session_id,
        topic=f"{topic_prefix}/{session_id}/cmd/velocity",
        command_timeout=float(values.get("MICRODUCK_COMMAND_TIMEOUT", "1.0")),
    )
