from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from device_agent_integration_demo.mqtt_config import DeviceAgentMqttConfig
from device_agent_integration_demo.mqtt_transport import DeviceAgentMqttTransport


class PublishInfo:
    def wait_for_publish(self, timeout: float) -> None:
        pass


class FakeClient:
    def __init__(self, **kwargs: Any):
        self.published: list[tuple[str, dict[str, Any], int, bool]] = []
        self.subscriptions: list[tuple[str, int]] = []

    def will_set(self, topic: str, payload: str, qos: int, retain: bool) -> None:
        self.will = (topic, json.loads(payload), qos, retain)

    def connect(self, host: str, port: int, keepalive: int) -> None:
        self.on_connect(self, None, None, 0, None)

    def loop_start(self) -> None:
        pass

    def loop_stop(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def subscribe(self, topic: str, qos: int) -> None:
        self.subscriptions.append((topic, qos))

    def publish(self, topic: str, payload: str, qos: int, retain: bool) -> PublishInfo:
        self.published.append((topic, json.loads(payload), qos, retain))
        return PublishInfo()


def config() -> DeviceAgentMqttConfig:
    return DeviceAgentMqttConfig("broker.test", 1883, False, "product", "device")


def test_command_response_state_event_and_duplicate(monkeypatch: Any) -> None:
    monkeypatch.setattr("device_agent_integration_demo.mqtt_transport.mqtt.Client", FakeClient)
    transport = DeviceAgentMqttTransport(config())
    transport.start({"motion_state": "idle"})
    client = transport._client
    payload = {"cmd": "kick", "params": {"foot": "left"}, "requestId": "req-1"}
    message = SimpleNamespace(retain=False, payload=json.dumps(payload).encode())

    client.on_message(client, None, message)
    pending = transport.poll()
    assert pending is not None
    transport.resolve(pending, {"code": 0, "msg": "accepted", "data": {"active_action": "kick"}})
    transport.publish_state(
        {"motion_state": "moving", "vx": 0.0, "vy": 0.0, "active_action": "kick"}
    )
    transport.publish_event({"event": "action_completed", "action": "kick"})
    client.on_message(client, None, message)

    response_messages = [item for item in client.published if item[0] == config().responses_topic]
    assert len(response_messages) == 2
    assert response_messages[0][1]["requestId"] == "req-1"
    assert response_messages[0][1]["metadata"]["productId"] == "product"
    assert transport.poll() is None
    assert any(item[1].get("type") == "state" for item in client.published)
    assert any(item[1].get("type") == "event" for item in client.published)
    transport.close()


def test_invalid_command_gets_400_response(monkeypatch: Any) -> None:
    monkeypatch.setattr("device_agent_integration_demo.mqtt_transport.mqtt.Client", FakeClient)
    transport = DeviceAgentMqttTransport(config())
    client = transport._client
    client.on_message(client, None, SimpleNamespace(retain=False, payload=b"[]"))
    topic, payload, _, _ = client.published[-1]
    assert topic == config().responses_topic
    assert payload["code"] == 400


def test_missing_request_id_is_rejected(monkeypatch: Any) -> None:
    monkeypatch.setattr("device_agent_integration_demo.mqtt_transport.mqtt.Client", FakeClient)
    transport = DeviceAgentMqttTransport(config())
    client = transport._client
    command = {"cmd": "kick", "params": {"foot": "left"}}
    client.on_message(client, None, SimpleNamespace(retain=False, payload=json.dumps(command).encode()))

    assert transport.poll() is None
    assert client.published[-1][1]["code"] == 400
    assert "requestId" in client.published[-1][1]["msg"]


def test_disconnect_timeout_is_reported_once_and_reset_on_reconnect(monkeypatch: Any) -> None:
    now = [10.0]
    monkeypatch.setattr("device_agent_integration_demo.mqtt_transport.mqtt.Client", FakeClient)
    monkeypatch.setattr("device_agent_integration_demo.mqtt_transport.time.monotonic", lambda: now[0])
    transport = DeviceAgentMqttTransport(config())
    transport.start(
        {"motion_state": "moving", "vx": 0.25, "vy": 0.0, "active_action": "move"}
    )
    client = transport._client

    client.on_disconnect(client, None, None, 1, None)
    now[0] += 0.99
    assert transport.poll_disconnect_timeout() is False
    now[0] += 0.01
    assert transport.poll_disconnect_timeout() is True
    assert transport.poll_disconnect_timeout() is False

    client.on_connect(client, None, None, 0, None)
    assert transport.poll_disconnect_timeout() is False
    transport.close()
