#!/usr/bin/env python3
"""Build the MQTT-enabled runner from the pinned upstream inference script."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor/microduck_rl/scripts/infer_policy.py"
TARGET = ROOT / ".generated/mqtt_infer_policy.py"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one upstream patch marker, found {count}: {old[:60]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    generated = replace_once(
        source,
        "import onnxruntime as ort\n",
        "import onnxruntime as ort\n\nfrom microduck_demo.mqtt_control import MqttVelocityBridge\n",
    )
    generated = replace_once(
        generated,
        "        policy.vel_max_ang = 1.5\n\n    # Set initial position to default pose",
        "        policy.vel_max_ang = 1.5\n\n"
        "    mqtt_bridge = MqttVelocityBridge.from_env()\n"
        "    mqtt_bridge.start()\n\n"
        "    # Set initial position to default pose",
    )
    generated = replace_once(
        generated,
        "                for key in term.get_keys():\n"
        "                    handle_key(key)\n\n"
        "                if not policy_enabled and policy_enable_time is not None:",
        "                for key in term.get_keys():\n"
        "                    handle_key(key)\n\n"
        "                mqtt_command = mqtt_bridge.poll()\n"
        "                if mqtt_command is not None:\n"
        "                    policy.set_vel_cmd(*mqtt_command)\n\n"
        "                if not policy_enabled and policy_enable_time is not None:",
    )
    generated = replace_once(
        generated,
        "    print(\"\\nInference stopped.\")",
        "    mqtt_bridge.close()\n\n    print(\"\\nInference stopped.\")",
    )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(generated, encoding="utf-8")
    TARGET.chmod(0o755)
    print(f"Generated {TARGET.relative_to(ROOT)} from pinned upstream source")


if __name__ == "__main__":
    main()
