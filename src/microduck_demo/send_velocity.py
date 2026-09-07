from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from typing import Any

import paho.mqtt.client as mqtt

from .config import load_config


PRESETS: dict[str, tuple[float, float, float]] = {
    "forward": (0.25, 0.0, 0.0),
    "forward-left": (0.25, 0.0, 0.8),
    "forward-right": (0.25, 0.0, -0.8),
    "stop": (0.0, 0.0, 0.0),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish safe Microduck velocity intents")
    parser.add_argument("action", nargs="?", choices=PRESETS, default="forward")
    parser.add_argument("--duration", type=float, default=2.0, help="Seconds to refresh the command")
    parser.add_argument("--rate", type=float, default=10.0, help="Publish rate in Hz")
    parser.add_argument("--vx", type=float, help="Forward speed from 0 to 0.25 m/s")
    parser.add_argument("--yaw", type=float, help="Turn rate from -0.8 to 0.8 rad/s; requires vx > 0")
    parser.add_argument(
        "--test-deadman",
        action="store_true",
        help="Simulation test only: omit the final stop and let the receiver timeout",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.duration < 0 or args.rate <= 0:
        raise SystemExit("--duration must be >= 0 and --rate must be > 0")

    vx, vy, yaw = PRESETS[args.action]
    vx = vx if args.vx is None else args.vx
    yaw = yaw if args.yaw is None else args.yaw
    if not 0.0 <= vx <= 0.25:
        raise SystemExit("--vx must be between 0 and 0.25 for the pinned walking policy")
    if not -0.8 <= yaw <= 0.8:
        raise SystemExit("--yaw must be between -0.8 and 0.8 for the pinned walking policy")
    if vx == 0.0 and yaw != 0.0:
        raise SystemExit("the pinned walking policy turns reliably only while moving forward")
    config = load_config()

    connected = threading.Event()
    failed: list[str] = []
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"microduck-controller-{config.session_id}-{uuid.uuid4().hex[:8]}",
        protocol=mqtt.MQTTv5,
    )

    def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code == 0:
            connected.set()
        else:
            failed.append(str(reason_code))
            connected.set()

    client.on_connect = on_connect
    client.connect(config.broker_host, config.broker_port, keepalive=30)
    client.loop_start()
    try:
        if not connected.wait(10) or failed:
            raise RuntimeError(f"MQTT connection failed: {failed[0] if failed else 'timeout'}")
        print(f"Publishing to {config.topic} at {args.rate:g} Hz for {args.duration:g} s")
        deadline = time.monotonic() + args.duration
        sequence = 0
        period = 1.0 / args.rate
        while time.monotonic() < deadline:
            payload = json.dumps(
                {"vx": vx, "vy": vy, "yaw": yaw, "seq": sequence, "ts": int(time.time() * 1000)},
                separators=(",", ":"),
            )
            client.publish(config.topic, payload, qos=0, retain=False)
            sequence += 1
            time.sleep(period)
    finally:
        if args.test_deadman:
            print("Deadman test: final zero velocity intentionally omitted")
        else:
            stop_payload = json.dumps(
                {"vx": 0.0, "vy": 0.0, "yaw": 0.0, "seq": sequence, "ts": int(time.time() * 1000)},
                separators=(",", ":"),
            )
            # QoS 0 is appropriate for a latest-value velocity stream, but one
            # packet can be lost. Repeat the final stop briefly; the receiver's
            # independent deadman remains the authoritative fallback.
            for _ in range(3):
                client.publish(config.topic, stop_payload, qos=0, retain=False).wait_for_publish(timeout=2)
                time.sleep(0.05)
        client.disconnect()
        client.loop_stop()
        if not args.test_deadman:
            print("Zero velocity published; disconnected")


if __name__ == "__main__":
    main()
