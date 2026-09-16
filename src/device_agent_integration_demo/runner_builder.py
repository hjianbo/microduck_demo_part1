"""Build an MQTT Device Agent runner from the pinned upstream inference script."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "vendor/microduck_rl/scripts/infer_policy.py"
TARGET = ROOT / ".generated/device_agent_integration_demo/infer_policy.py"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one upstream patch marker, found {count}: {old[:70]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    generated = SOURCE.read_text(encoding="utf-8")
    generated = replace_once(
        generated,
        "import onnxruntime as ort\n",
        "import onnxruntime as ort\n\n"
        "from device_agent_integration_demo.action_controller import ActionController\n"
        "from device_agent_integration_demo.commands import CommandError\n"
        "from device_agent_integration_demo.mqtt_transport import DeviceAgentMqttTransport\n"
        "from device_agent_integration_demo.runtime import PolicyRuntime\n",
    )
    generated = replace_once(
        generated,
        "    args = parser.parse_args()\n",
        "    parser.add_argument('--ball-seed', type=int, default=None)\n"
        "    parser.add_argument('--ball-rolling-friction', type=float, default=0.01,\n"
        "                        help='Ball rolling friction (default: 0.01; upstream is 0.0001)')\n"
        "    parser.add_argument('--ball-velocity-damping', type=float, default=3.0,\n"
        "                        help='Smooth damping after kick contact, per second (default: 3.0)')\n"
        "    args = parser.parse_args()\n",
    )
    generated = replace_once(
        generated,
        "    # Initialize policy\n",
        "    if not 0.0 <= args.ball_rolling_friction <= 0.05:\n"
        "        parser.error('--ball-rolling-friction must be between 0 and 0.05')\n"
        "    if not 0.0 <= args.ball_velocity_damping <= 20.0:\n"
        "        parser.error('--ball-velocity-damping must be between 0 and 20')\n"
        "    ball_geom_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, 'ball_geom')\n"
        "    if ball_geom_id >= 0:\n"
        "        upstream_rolling_friction = float(model.geom_friction[ball_geom_id, 2])\n"
        "        model.geom_friction[ball_geom_id, 2] = args.ball_rolling_friction\n"
        "        print(f'Ball rolling friction: {upstream_rolling_friction:g} -> '\n"
        "              f'{args.ball_rolling_friction:g}')\n\n"
        "    # Initialize policy\n",
    )
    generated = replace_once(
        generated,
        "    # Verify observation size\n",
        "    demo_runtime = PolicyRuntime(\n"
        "        policy, data, seed=args.ball_seed,\n"
        "        ball_velocity_damping=args.ball_velocity_damping,\n"
        "        model=model, ball_geom_id=ball_geom_id,\n"
        "    )\n"
        "    demo_mqtt = DeviceAgentMqttTransport.from_env()\n"
        "    demo_controller = ActionController(\n"
        "        demo_runtime, command_timeout_s=demo_mqtt.config.command_timeout,\n"
        "    )\n"
        "    demo_mqtt.start(demo_controller.telemetry_snapshot())\n"
        "    demo_last_state = demo_controller.telemetry_snapshot()\n\n"
        "    # Verify observation size\n",
    )
    generated = replace_once(
        generated,
        "                policy.update_ground_pick_phase(actual_dt)\n"
        "                policy.update_behavior(actual_dt)\n\n",
        "                if demo_mqtt.poll_disconnect_timeout():\n"
        "                    demo_controller.handle_command_timeout()\n"
        "                pending = demo_mqtt.poll()\n"
        "                while pending is not None:\n"
        "                    try:\n"
        "                        if pending.payload.get('cmd') == 'status':\n"
        "                            result = {'code': 0, 'msg': 'ok', 'data': demo_controller.snapshot()}\n"
        "                        else:\n"
        "                            result = demo_controller.submit_payload(pending.payload).to_dict()\n"
        "                    except CommandError as exc:\n"
        "                        result = {'code': 400, 'msg': str(exc), 'data': demo_controller.snapshot()}\n"
        "                    except Exception as exc:\n"
        "                        result = {'code': 500, 'msg': str(exc), 'data': demo_controller.snapshot()}\n"
        "                    demo_mqtt.resolve(pending, result)\n"
        "                    # Device Agent requires a fresh state report after every command,\n"
        "                    # including repeated commands whose values did not change.\n"
        "                    demo_state = demo_controller.telemetry_snapshot()\n"
        "                    demo_mqtt.publish_state(demo_state)\n"
        "                    demo_last_state = demo_state\n"
        "                    pending = demo_mqtt.poll()\n\n"
        "                policy.update_ground_pick_phase(actual_dt)\n"
        "                policy.update_behavior(actual_dt)\n"
        "                demo_controller.update(actual_dt)\n"
        "                demo_state = demo_controller.telemetry_snapshot()\n"
        "                if demo_state != demo_last_state:\n"
        "                    demo_mqtt.publish_state(demo_state)\n"
        "                    demo_last_state = demo_state\n"
        "                for demo_event in demo_controller.drain_events():\n"
        "                    demo_mqtt.publish_event(demo_event)\n\n",
    )
    generated = replace_once(
        generated,
        "    print(\"\\nInference stopped.\")",
        "    demo_mqtt.close()\n\n    print(\"\\nInference stopped.\")",
    )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(generated, encoding="utf-8")
    TARGET.chmod(0o755)
    print(f"Generated {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
