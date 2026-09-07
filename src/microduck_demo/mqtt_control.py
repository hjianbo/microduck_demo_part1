from __future__ import annotations

import atexit
import json
import math
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from .config import DemoConfig, load_config


class MqttVelocityBridge:
    """Receive the newest safe velocity intent without blocking MuJoCo."""

    VX_LIMIT = 0.25
    YAW_LIMIT = 0.8

    def __init__(self, config: DemoConfig):
        self.config = config
        self._lock = threading.Lock()
        self._latest: tuple[float, float, float] | None = None
        self._received_at = 0.0
        self._version = 0
        self._applied_version = 0
        self._timeout_applied = True
        self._force_stop = False
        self._closed = False
        self._connected = threading.Event()
        self._connect_error: str | None = None
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"microduck-sim-{config.session_id}",
            protocol=mqtt.MQTTv5,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @classmethod
    def from_env(cls) -> "MqttVelocityBridge":
        return cls(load_config())

    def start(self) -> None:
        print(
            f"MQTT: connecting to {self.config.broker_host}:{self.config.broker_port}; "
            f"topic={self.config.topic}; retain=false"
        )
        self._client.connect(self.config.broker_host, self.config.broker_port, keepalive=30)
        self._client.loop_start()
        if not self._connected.wait(10):
            self.close()
            raise TimeoutError("MQTT connection timed out")
        if self._connect_error is not None:
            self.close()
            raise ConnectionError(f"MQTT connection rejected: {self._connect_error}")
        atexit.register(self.close)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def poll(self) -> tuple[float, float, float] | None:
        """Return a new command, or one zero command when it expires/disconnects."""
        now = time.monotonic()
        with self._lock:
            if self._force_stop:
                self._force_stop = False
                self._timeout_applied = True
                return (0.0, 0.0, 0.0)
            if self._version != self._applied_version and self._latest is not None:
                self._applied_version = self._version
                self._timeout_applied = self._latest == (0.0, 0.0, 0.0)
                return self._latest
            if (
                self._latest is not None
                and not self._timeout_applied
                and now - self._received_at >= self.config.command_timeout
            ):
                self._timeout_applied = True
                print("MQTT: command timeout; velocity reset to zero")
                return (0.0, 0.0, 0.0)
        return None

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code != 0:
            self._connect_error = str(reason_code)
            self._connected.set()
            return
        client.subscribe(self.config.topic, qos=0)
        self._connected.set()
        print(f"MQTT: connected and subscribed to {self.config.topic}")

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
        if self._closed:
            return
        with self._lock:
            self._force_stop = True
        print(f"MQTT: disconnected ({reason_code}); requesting zero velocity")

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        if message.retain:
            print("MQTT: ignored retained velocity message")
            return
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            command = self._validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"MQTT: ignored invalid command: {exc}")
            return

        with self._lock:
            self._latest = command
            self._received_at = time.monotonic()
            self._version += 1

    @classmethod
    def _validate(cls, payload: Any) -> tuple[float, float, float]:
        if not isinstance(payload, dict):
            raise TypeError("payload must be a JSON object")
        unknown = set(payload) - {"vx", "vy", "yaw", "seq", "ts"}
        if unknown:
            raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")

        values: dict[str, float] = {}
        for field in ("vx", "vy", "yaw"):
            value = payload.get(field, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field} must be a number")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"{field} must be finite")
            values[field] = number

        if values["vx"] < 0.0:
            raise ValueError("vx must be non-negative for the pinned walking policy")
        if values["vy"] != 0.0:
            raise ValueError("vy must be zero: the pinned walking policy does not support strafing")
        if values["vx"] == 0.0 and values["yaw"] != 0.0:
            raise ValueError("turning requires positive vx with the pinned walking policy")

        return (
            min(cls.VX_LIMIT, values["vx"]),
            0.0,
            max(-cls.YAW_LIMIT, min(cls.YAW_LIMIT, values["yaw"])),
        )
