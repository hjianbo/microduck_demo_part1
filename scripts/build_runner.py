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
        "import onnxruntime as ort\n\n"
        "from microduck_demo.ball_seek import BallSeekController\n"
        "from microduck_demo.mqtt_control import MqttVelocityBridge\n",
    )
    generated = replace_once(
        generated,
        'MICRODUCK_BALL_XML = "src/mjlab_microduck/robot/microduck/scene_ball.xml"\n',
        'MICRODUCK_BALL_XML = "src/mjlab_microduck/robot/microduck/scene_ball.xml"\n'
        'MICRODUCK_ALLCOLLISIONS_XML = '
        '"src/mjlab_microduck/robot/microduck/scene_allcollisions.xml"\n',
    )
    generated = replace_once(
        generated,
        "    args = parser.parse_args()\n",
        "    parser.add_argument(\"--auto-ball\", action=\"store_true\",\n"
        "                        help=\"Privileged MuJoCo demo: search for a random ball, \"\n"
        "                             \"approach it, and trigger the kick policy\")\n"
        "    parser.add_argument(\"--ball-seed\", type=int, default=None,\n"
        "                        help=\"Random seed for --auto-ball ball placement\")\n"
        "    args = parser.parse_args()\n"
        "    if args.auto_ball and not (args.kick_left or args.kick_right):\n"
        "        parser.error(\"--auto-ball requires --kick-left and/or --kick-right\")\n"
        "    if args.auto_ball and args.kick_duration == 3.0:\n"
        "        args.kick_duration = 0.5\n",
    )
    generated = replace_once(
        generated,
        "    def trigger_behavior(self, name):\n",
        "    def trigger_behavior(self, name, place_ball=True):\n",
    )
    generated = replace_once(
        generated,
        "        if name in (\"kick_left\", \"kick_right\"):\n            self._place_ball(name)\n",
        "        if place_ball and name in (\"kick_left\", \"kick_right\"):\n            self._place_ball(name)\n",
    )
    generated = replace_once(
        generated,
        "    if args.scene:\n        xml_path = args.scene\n    elif args.roller:\n",
        "    if args.scene:\n"
        "        xml_path = args.scene\n"
        "    elif args.auto_ball:\n"
        "        # Match the official browser simulator, where this shipped\n"
        "        # walking policy uses all-collision MJCF position actuators.\n"
        "        xml_path = MICRODUCK_ALLCOLLISIONS_XML\n"
        "        if not args.no_bam:\n"
        "            print(\"AUTO-BALL: using browser-compatible --no-bam physics\")\n"
        "            args.no_bam = True\n"
        "    elif args.roller:\n",
    )
    generated = replace_once(
        generated,
        "    else:\n"
        "        model = mujoco.MjModel.from_xml_path(xml_path)\n"
        "        model.opt.timestep = 0.005\n"
        "        data = mujoco.MjData(model)\n"
        "        print(\"Legacy MuJoCo position actuators (--no-bam): NOT the actuator the policy was trained with\")\n",
        "    else:\n"
        "        if args.auto_ball:\n"
        "            spec = mujoco.MjSpec.from_file(xml_path)\n"
        "            ball = spec.worldbody.add_body(\n"
        "                name=\"ball\", pos=[0.3, 0.0, BALL_RADIUS])\n"
        "            ball.add_freejoint(name=\"ball_free\")\n"
        "            ball.add_geom(\n"
        "                name=\"ball_geom\", type=mujoco.mjtGeom.mjGEOM_SPHERE,\n"
        "                size=[BALL_RADIUS, 0.0, 0.0], mass=0.015,\n"
        "                friction=[0.5, 0.005, 0.0001],\n"
        "                rgba=[1.0, 0.55, 0.0, 1.0],\n"
        "            )\n"
        "            model = spec.compile()\n"
        "        else:\n"
        "            model = mujoco.MjModel.from_xml_path(xml_path)\n"
        "        model.opt.timestep = 0.005\n"
        "        data = mujoco.MjData(model)\n"
        "        print(\"Legacy MuJoCo position actuators (--no-bam): NOT the actuator the policy was trained with\")\n",
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
        "    mujoco.mj_forward(model, data)\n\n    # Verify observation size",
        "    mujoco.mj_forward(model, data)\n\n"
        "    auto_ball = None\n"
        "    if args.auto_ball:\n"
        "        auto_ball = BallSeekController(\n"
        "            mujoco=mujoco, model=model, data=data, policy=policy,\n"
        "            trunk_qpos_adr=qpos_adr,\n"
        "            trunk_qvel_adr=int(model.jnt_dofadr[freejoint_id]),\n"
        "            seed=args.ball_seed,\n"
        "        )\n"
        "        auto_ball.start()\n\n"
        "    # Verify observation size",
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
        "                policy.update_ground_pick_phase(actual_dt)\n"
        "                policy.update_behavior(actual_dt)\n\n"
        "                if policy_enabled:",
        "                policy.update_ground_pick_phase(actual_dt)\n"
        "                policy.update_behavior(actual_dt)\n"
        "                if auto_ball is not None:\n"
        "                    auto_ball.update(actual_dt)\n\n"
        "                if policy_enabled:",
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
