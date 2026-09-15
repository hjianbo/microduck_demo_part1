from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading
import time
from typing import Any
import uuid

import paho.mqtt.client as mqtt

from .mqtt_config import DeviceAgentMqttConfig, configure_client, load_mqtt_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control the Microduck simulator over Device Agent MQTT topics")
    parser.add_argument("--config", type=Path, help="Path to a Device Agent MQTT env file")
    parser.add_argument("--timeout", type=float, default=6.0, help="Seconds to wait for a matching response")
    sub = parser.add_subparsers(dest="command", required=True)

    move = sub.add_parser("move")
    move.add_argument("direction", choices=("forward", "left", "right", "backward"))
    move.add_argument("--duration", type=float, default=2.0)
    sub.add_parser("stop")

    kick = sub.add_parser("kick")
    kick.add_argument("foot", choices=("left", "right"))

    ball = sub.add_parser("place-ball")
    ball.add_argument("position", choices=("center", "left_kick", "right_kick", "random"), default="center", nargs="?")
    sub.add_parser("status")
    return parser


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "move":
        return {"cmd": "move", "params": {"direction": args.direction, "duration_s": args.duration}}
    if args.command == "kick":
        return {"cmd": "kick", "params": {"foot": args.foot}}
    if args.command == "place-ball":
        return {"cmd": "place_ball", "params": {"position": args.position}}
    return {"cmd": args.command, "params": {}}


def send(payload: dict[str, Any], config: DeviceAgentMqttConfig, timeout: float = 6.0) -> dict[str, Any]:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    request_id = payload.get("requestId") or f"cli-{uuid.uuid4().hex}"
    command = {
        **payload,
        "requestId": request_id,
        "ts": int(time.time() * 1000),
        "metadata": {"productId": config.product_id, "source": "microduck-demo-cli"},
    }
    connected = threading.Event()
    subscribed = threading.Event()
    completed = threading.Event()
    failure: list[str] = []
    response: list[dict[str, Any]] = []
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"microduck-cli-{config.device_id}-{uuid.uuid4().hex[:8]}",
        protocol=mqtt.MQTTv5,
    )
    configure_client(client, config)

    def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code != 0:
            failure.append(str(reason_code))
            connected.set()
            return
        client.subscribe(config.responses_topic, qos=config.qos)
        connected.set()

    def on_subscribe(client: mqtt.Client, userdata: Any, mid: int, reason_codes: Any, properties: Any) -> None:
        subscribed.set()

    def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            decoded = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(decoded, dict) and decoded.get("requestId") == request_id:
            response.append(decoded)
            completed.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.connect(config.broker_host, config.broker_port, config.keepalive)
    client.loop_start()
    try:
        if not connected.wait(timeout) or failure:
            raise RuntimeError(f"MQTT connection failed: {failure[0] if failure else 'timeout'}")
        if not subscribed.wait(timeout):
            raise TimeoutError(f"subscription timed out: {config.responses_topic}")
        info = client.publish(
            config.commands_topic,
            json.dumps(command, ensure_ascii=False, separators=(",", ":")),
            qos=config.qos,
            retain=False,
        )
        info.wait_for_publish(timeout=timeout)
        if not completed.wait(timeout):
            raise TimeoutError(f"no response for requestId={request_id} within {timeout:g}s")
        return response[0]
    finally:
        client.disconnect()
        client.loop_stop()


def main() -> None:
    args = _parser().parse_args()
    try:
        config = load_mqtt_config(args.config)
        response = send(build_payload(args), config, args.timeout)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"MQTT command failed: {exc}") from exc
    print(json.dumps(response, ensure_ascii=False, indent=2))
    if response.get("code") != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
