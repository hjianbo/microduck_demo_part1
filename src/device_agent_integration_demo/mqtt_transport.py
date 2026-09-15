from __future__ import annotations

import atexit
from collections import OrderedDict
from dataclasses import dataclass
import json
import queue
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from .mqtt_config import DeviceAgentMqttConfig, configure_client, load_mqtt_config


SOURCE = "microduck-simulator"


@dataclass(frozen=True)
class PendingCommand:
    payload: dict[str, Any]
    request_id: str


class DeviceAgentMqttTransport:
    """Thread-safe Device Agent MQTT edge adapter for the MuJoCo main loop."""

    def __init__(self, config: DeviceAgentMqttConfig):
        self.config = config
        self.mailbox: queue.Queue[PendingCommand] = queue.Queue(maxsize=32)
        self._connected = threading.Event()
        self._connect_error: str | None = None
        self._closed = False
        self._initial_state: dict[str, Any] = {}
        self._completed: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._disconnected_at: float | None = None
        self._disconnect_timeout_reported = False
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"microduck-sim-{config.device_id}",
            protocol=mqtt.MQTTv5,
        )
        configure_client(self._client, config)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @classmethod
    def from_env(cls) -> "DeviceAgentMqttTransport":
        return cls(load_mqtt_config())

    def start(self, initial_state: dict[str, Any]) -> None:
        self._initial_state = initial_state.copy()
        self._client.will_set(
            self.config.telemetry_topic,
            self._encode(self._status_payload("offline", self._initial_state)),
            qos=self.config.qos,
            retain=True,
        )
        print(
            f"Device Agent MQTT: connecting to {self.config.broker_host}:{self.config.broker_port}; "
            f"commands={self.config.commands_topic}"
        )
        self._client.connect(self.config.broker_host, self.config.broker_port, self.config.keepalive)
        self._client.loop_start()
        if not self._connected.wait(10):
            self.close()
            raise TimeoutError("Device Agent MQTT connection timed out")
        if self._connect_error is not None:
            self.close()
            raise ConnectionError(f"Device Agent MQTT connection rejected: {self._connect_error}")
        atexit.register(self.close)

    def poll(self) -> PendingCommand | None:
        try:
            return self.mailbox.get_nowait()
        except queue.Empty:
            return None

    def poll_disconnect_timeout(self) -> bool:
        """Return true once when an MQTT outage exceeds the safety timeout."""
        with self._lock:
            if (
                self._disconnected_at is None
                or self._disconnect_timeout_reported
                or time.monotonic() - self._disconnected_at < self.config.command_timeout
            ):
                return False
            self._disconnect_timeout_reported = True
            return True

    def resolve(self, pending: PendingCommand, result: dict[str, Any]) -> None:
        response = {
            "code": result["code"],
            "msg": result["msg"],
            "requestId": pending.request_id,
            "data": result.get("data", {}),
            "ts": self._now_ms(),
            "metadata": self._metadata(),
        }
        if pending.request_id:
            with self._lock:
                self._inflight.discard(pending.request_id)
                self._completed[pending.request_id] = response
                self._completed.move_to_end(pending.request_id)
                while len(self._completed) > 128:
                    self._completed.popitem(last=False)
        self._publish(self.config.responses_topic, response)

    def publish_state(self, state: dict[str, Any]) -> None:
        self._initial_state = state.copy()
        self._publish(
            self.config.telemetry_topic,
            {"type": "state", "data": state, "ts": self._now_ms(), "metadata": self._metadata()},
        )

    def publish_event(self, event: dict[str, Any]) -> None:
        self._publish(
            self.config.events_topic,
            {"type": "event", "data": event, "ts": self._now_ms(), "metadata": self._metadata()},
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._connected.is_set() and self._connect_error is None:
            info = self._client.publish(
                self.config.telemetry_topic,
                self._encode(self._status_payload("offline", self._initial_state)),
                qos=self.config.qos,
                retain=True,
            )
            info.wait_for_publish(timeout=2)
            self._client.disconnect()
        self._client.loop_stop()

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code != 0:
            self._connect_error = str(reason_code)
            self._connected.set()
            return
        with self._lock:
            self._disconnected_at = None
            self._disconnect_timeout_reported = False
        client.subscribe(self.config.commands_topic, qos=self.config.qos)
        client.publish(
            self.config.telemetry_topic,
            self._encode(self._status_payload("online", self._initial_state)),
            qos=self.config.qos,
            retain=True,
        )
        self._connected.set()
        print(f"Device Agent MQTT: connected and subscribed to {self.config.commands_topic}")

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if not self._closed:
            self._connected.clear()
            with self._lock:
                if self._disconnected_at is None:
                    self._disconnected_at = time.monotonic()
            print(f"Device Agent MQTT: disconnected ({reason_code})")

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        if message.retain:
            print("Device Agent MQTT: ignored retained command")
            return
        request_id = ""
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("command payload must be a JSON object")
            raw_request_id = payload.get("requestId")
            if not isinstance(raw_request_id, str) or not raw_request_id.strip():
                raise ValueError("requestId must be a non-empty string")
            request_id = raw_request_id
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._publish_error(request_id, 400, str(exc))
            return

        if request_id:
            with self._lock:
                completed = self._completed.get(request_id)
                if completed is not None:
                    self._publish(self.config.responses_topic, completed)
                    return
                if request_id in self._inflight:
                    return
                self._inflight.add(request_id)
        try:
            self.mailbox.put_nowait(PendingCommand(payload, request_id))
        except queue.Full:
            with self._lock:
                self._inflight.discard(request_id)
            self._publish_error(request_id, 503, "simulator command queue is full")

    def _publish_error(self, request_id: str, code: int, msg: str) -> None:
        self._publish(
            self.config.responses_topic,
            {
                "code": code,
                "msg": msg,
                "requestId": request_id,
                "data": {},
                "ts": self._now_ms(),
                "metadata": self._metadata(),
            },
        )

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        self._client.publish(topic, self._encode(payload), qos=self.config.qos, retain=False)

    def _status_payload(self, status: str, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "status",
            "data": {"status": status, "state": state},
            "ts": self._now_ms(),
            "metadata": self._metadata(),
        }

    def _metadata(self) -> dict[str, str]:
        return {"productId": self.config.product_id, "source": SOURCE}

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
