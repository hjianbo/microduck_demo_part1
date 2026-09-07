#!/usr/bin/env python3
"""Optional live check against the configured MQTT broker."""

from pathlib import Path
import os
import subprocess
import sys
import time

from microduck_demo.mqtt_control import MqttVelocityBridge


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault(
        "MICRODUCK_MQTT_CONFIG", str(root / ".demo/session.env")
    )
    bridge = MqttVelocityBridge.from_env()
    bridge.start()
    started = time.monotonic()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "microduck_demo.send_velocity",
            "turn-left",
            "--duration",
            "0.5",
            "--rate",
            "10",
        ],
        cwd=root,
    )
    saw_motion = False
    saw_stop = False
    deadline = started + 20
    try:
        while time.monotonic() < deadline:
            command = bridge.poll()
            if command is not None:
                print(f"received: {command}")
                if command == (0.0, 0.0, 0.0):
                    saw_stop = saw_motion
                    if saw_stop:
                        break
                else:
                    saw_motion = True
            time.sleep(0.02)
    finally:
        process.wait(timeout=10)
        bridge.close()
    if not saw_motion or not saw_stop:
        raise SystemExit("Broker check failed: did not observe motion followed by stop")
    print("Broker check passed: isolated Topic received motion followed by stop")


if __name__ == "__main__":
    main()
