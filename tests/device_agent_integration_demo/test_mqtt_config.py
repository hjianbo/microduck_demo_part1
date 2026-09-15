from pathlib import Path

import pytest

from device_agent_integration_demo.mqtt_config import load_mqtt_config


def test_loads_device_agent_topics_and_tls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVICE_AGENT_MQTT_CONFIG", raising=False)
    path = tmp_path / "mqtt.env"
    path.write_text(
        "\n".join(
            [
                "DEVICE_AGENT_BROKER=mqtts://example.test:8883",
                "DEVICE_AGENT_PRODUCT_ID=duck-product",
                "DEVICE_AGENT_DEVICE_ID=duck-01",
                "DEVICE_AGENT_USERNAME=demo-user",
                "DEVICE_AGENT_PASSWORD=secret",
                "DEVICE_AGENT_COMMAND_TIMEOUT=1.5",
            ]
        ),
        encoding="utf-8",
    )

    config = load_mqtt_config(path)

    assert config.tls is True
    assert config.commands_topic == "device-agent/duck-product/device/duck-01/commands"
    assert config.responses_topic == "device-agent/duck-product/device/duck-01/responses"
    assert config.telemetry_topic == "v1/duck-product/duck-01/telemetry"
    assert config.events_topic == "v1/duck-product/duck-01/event"
    assert config.command_timeout == 1.5


def test_rejects_non_mqtt_broker(tmp_path: Path) -> None:
    path = tmp_path / "mqtt.env"
    path.write_text(
        "DEVICE_AGENT_BROKER=https://example.test\n"
        "DEVICE_AGENT_PRODUCT_ID=p\n"
        "DEVICE_AGENT_DEVICE_ID=d\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mqtt://"):
        load_mqtt_config(path)
