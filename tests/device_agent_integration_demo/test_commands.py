import math

import pytest

from device_agent_integration_demo.commands import (
    CommandError,
    Direction,
    Foot,
    KickCommand,
    MoveCommand,
    PlaceBallCommand,
    StopCommand,
    parse_command,
)


def test_parses_public_commands() -> None:
    assert parse_command({"cmd": "move", "params": {"direction": "left"}}) == MoveCommand(Direction.LEFT)
    assert parse_command(
        {"cmd": "move", "params": {"direction": "left", "duration_s": 30.0}}
    ) == MoveCommand(Direction.LEFT, 30.0)
    assert parse_command({"cmd": "kick", "params": {"foot": "right"}}) == KickCommand(Foot.RIGHT)
    assert isinstance(parse_command({"cmd": "stop"}), StopCommand)
    assert isinstance(parse_command({"cmd": "reset_ball"}), PlaceBallCommand)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"cmd": "dance"},
        {"cmd": "move", "params": {}},
        {"cmd": "move", "params": {"direction": "sideways"}},
        {"cmd": "move", "params": {"direction": "forward", "duration_s": True}},
        {"cmd": "move", "params": {"direction": "forward", "duration_s": math.inf}},
        {"cmd": "move", "params": {"direction": "forward", "duration_s": 30.1}},
        {"cmd": "kick", "params": {"foot": "middle"}},
        {"cmd": "stop", "params": {"now": True}},
        {"cmd": "stop", "unexpected": 1},
    ],
)
def test_rejects_invalid_commands(payload: object) -> None:
    with pytest.raises(CommandError):
        parse_command(payload)
