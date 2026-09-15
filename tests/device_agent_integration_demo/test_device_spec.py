import json
from pathlib import Path
import subprocess
import sys

from device_agent_integration_demo.commands import BallPosition, Direction, Foot, parse_command


SPEC = Path("src/device_agent_integration_demo/device-spec.json")


def test_device_spec_is_valid_json_and_matches_parser() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert set(spec) == {"name", "description", "commands", "properties", "events"}
    assert set(spec["commands"]) == {"move", "stop", "kick", "place_ball"}
    assert set(spec["properties"]) == {
        "motion_state", "vx", "yaw", "active_action", "kick_side",
        "ball_state", "last_action_result", "command_timeout_s",
    }
    assert set(spec["events"]) == {"action_completed", "action_failed", "command_timeout"}

    for direction in Direction:
        parse_command({"cmd": "move", "params": {"direction": direction.value}})
    for foot in Foot:
        parse_command({"cmd": "kick", "params": {"foot": foot.value}})
    for position in BallPosition:
        parse_command({"cmd": "place_ball", "params": {"position": position.value}})


def test_generated_runner_overrides_ball_rolling_friction() -> None:
    subprocess.run(
        [sys.executable, "-m", "device_agent_integration_demo.runner_builder"],
        check=True,
    )
    runner = Path(".generated/device_agent_integration_demo/infer_policy.py").read_text(encoding="utf-8")
    assert "--ball-rolling-friction" in runner
    assert "default=0.01" in runner
    assert "model.geom_friction[ball_geom_id, 2] = args.ball_rolling_friction" in runner
    assert "--ball-velocity-damping" in runner
    assert "ball_velocity_damping=args.ball_velocity_damping" in runner
    assert "model=model, ball_geom_id=ball_geom_id" in runner
