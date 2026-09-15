import json
from pathlib import Path

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
