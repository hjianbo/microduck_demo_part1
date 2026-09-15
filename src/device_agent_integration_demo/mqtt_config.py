from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import ssl
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class DeviceAgentMqttConfig:
    broker_host: str
    broker_port: int
    tls: bool
    product_id: str
    device_id: str
    username: str | None = None
    password: str | None = None
    qos: int = 1
    keepalive: int = 30
    command_timeout: float = 1.0

    @property
    def commands_topic(self) -> str:
        return f"device-agent/{self.product_id}/device/{self.device_id}/commands"

    @property
    def responses_topic(self) -> str:
        return f"device-agent/{self.product_id}/device/{self.device_id}/responses"

    @property
    def telemetry_topic(self) -> str:
        return f"v1/{self.product_id}/{self.device_id}/telemetry"

    @property
    def events_topic(self) -> str:
        return f"v1/{self.product_id}/{self.device_id}/event"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid config line {line_number} in {path}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_mqtt_config(path: str | Path | None = None) -> DeviceAgentMqttConfig:
    configured_path = path or os.environ.get("DEVICE_AGENT_MQTT_CONFIG")
    default_path = Path(__file__).resolve().parents[2] / ".demo/device-agent.env"
    if not configured_path and default_path.is_file():
        configured_path = default_path
    values: dict[str, str] = {}
    if configured_path:
        config_path = Path(configured_path).expanduser().resolve()
        if not config_path.is_file():
            raise FileNotFoundError(f"Device Agent MQTT config not found: {config_path}")
        values.update(_parse_env_file(config_path))

    # Process environment values intentionally override the local config file.
    for key in (
        "DEVICE_AGENT_BROKER",
        "DEVICE_AGENT_PRODUCT_ID",
        "DEVICE_AGENT_DEVICE_ID",
        "DEVICE_AGENT_USERNAME",
        "DEVICE_AGENT_PASSWORD",
        "DEVICE_AGENT_MQTT_QOS",
        "DEVICE_AGENT_MQTT_KEEPALIVE",
        "DEVICE_AGENT_COMMAND_TIMEOUT",
    ):
        if key in os.environ:
            values[key] = os.environ[key]

    missing = [
        key
        for key in ("DEVICE_AGENT_BROKER", "DEVICE_AGENT_PRODUCT_ID", "DEVICE_AGENT_DEVICE_ID")
        if not values.get(key)
    ]
    if missing:
        raise RuntimeError(
            f"missing MQTT configuration: {', '.join(missing)}; "
            "run ./scripts/bootstrap.sh or set DEVICE_AGENT_MQTT_CONFIG"
        )

    parsed = urlparse(values["DEVICE_AGENT_BROKER"])
    if parsed.scheme not in {"mqtt", "mqtts"} or not parsed.hostname:
        raise ValueError("DEVICE_AGENT_BROKER must be mqtt://host[:port] or mqtts://host[:port]")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("DEVICE_AGENT_BROKER must not contain credentials, a path, query, or fragment")

    for key in ("DEVICE_AGENT_PRODUCT_ID", "DEVICE_AGENT_DEVICE_ID"):
        value = values[key]
        if value.strip() != value or any(character in value for character in "/+#"):
            raise ValueError(f"{key} must be one MQTT topic segment without whitespace or /+#")

    qos = int(values.get("DEVICE_AGENT_MQTT_QOS", "1"))
    keepalive = int(values.get("DEVICE_AGENT_MQTT_KEEPALIVE", "30"))
    command_timeout = float(values.get("DEVICE_AGENT_COMMAND_TIMEOUT", "1.0"))
    if qos not in {0, 1, 2}:
        raise ValueError("DEVICE_AGENT_MQTT_QOS must be 0, 1, or 2")
    if not 5 <= keepalive <= 65535:
        raise ValueError("DEVICE_AGENT_MQTT_KEEPALIVE must be between 5 and 65535")
    if not 0.2 <= command_timeout <= 10.0:
        raise ValueError("DEVICE_AGENT_COMMAND_TIMEOUT must be between 0.2 and 10.0 seconds")

    tls = parsed.scheme == "mqtts"
    return DeviceAgentMqttConfig(
        broker_host=parsed.hostname,
        broker_port=parsed.port or (8883 if tls else 1883),
        tls=tls,
        product_id=values["DEVICE_AGENT_PRODUCT_ID"],
        device_id=values["DEVICE_AGENT_DEVICE_ID"],
        username=values.get("DEVICE_AGENT_USERNAME") or None,
        password=values.get("DEVICE_AGENT_PASSWORD") or None,
        qos=qos,
        keepalive=keepalive,
        command_timeout=command_timeout,
    )


def configure_client(client: Any, config: DeviceAgentMqttConfig) -> None:
    if config.username is not None:
        client.username_pw_set(config.username, config.password)
    if config.tls:
        client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
