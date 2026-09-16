from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Any


class CommandError(ValueError):
    """A command does not conform to the demo's public command contract."""


class Direction(StrEnum):
    FORWARD = "forward"
    LEFT = "left"
    RIGHT = "right"
    BACKWARD = "backward"


class Foot(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class BallPosition(StrEnum):
    CENTER = "center"
    LEFT_KICK = "left_kick"
    RIGHT_KICK = "right_kick"
    RANDOM = "random"


@dataclass(frozen=True)
class MoveCommand:
    direction: Direction
    duration_s: float = 2.0
    name: str = "move"


@dataclass(frozen=True)
class StopCommand:
    name: str = "stop"


@dataclass(frozen=True)
class KickCommand:
    foot: Foot
    name: str = "kick"


@dataclass(frozen=True)
class PlaceBallCommand:
    position: BallPosition = BallPosition.CENTER
    name: str = "place_ball"


DemoCommand = MoveCommand | StopCommand | KickCommand | PlaceBallCommand

MIN_MOVE_DURATION_S = 0.2
MAX_MOVE_DURATION_S = 30.0


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandError(f"{label} must be a JSON object")
    return value


def _only(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise CommandError(f"unknown {label} fields: {', '.join(sorted(unknown))}")


def _enum(enum_type: type[StrEnum], value: Any, label: str) -> Any:
    if not isinstance(value, str):
        raise CommandError(f"{label} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise CommandError(f"{label} must be one of: {choices}") from exc


def parse_command(payload: Any) -> DemoCommand:
    """Parse the same cmd/params shape that Device Agent publishes."""
    obj = _object(payload, "command")
    _only(obj, {"cmd", "params", "requestId", "ts", "metadata"}, "command")
    name = obj.get("cmd")
    if not isinstance(name, str):
        raise CommandError("cmd must be a string")
    params = _object(obj.get("params", {}), "params")

    if name == "move":
        _only(params, {"direction", "duration_s"}, "move params")
        direction = _enum(Direction, params.get("direction"), "direction")
        duration = params.get("duration_s", 2.0)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise CommandError("duration_s must be a number")
        duration = float(duration)
        if not math.isfinite(duration) or not MIN_MOVE_DURATION_S <= duration <= MAX_MOVE_DURATION_S:
            raise CommandError(
                f"duration_s must be finite and between {MIN_MOVE_DURATION_S} and "
                f"{MAX_MOVE_DURATION_S}"
            )
        return MoveCommand(direction=direction, duration_s=duration)

    if name == "stop":
        _only(params, set(), "stop params")
        return StopCommand()

    if name == "kick":
        _only(params, {"foot"}, "kick params")
        return KickCommand(foot=_enum(Foot, params.get("foot"), "foot"))

    if name in {"place_ball", "reset_ball"}:
        _only(params, {"position"}, "place_ball params")
        position = _enum(BallPosition, params.get("position", "center"), "position")
        return PlaceBallCommand(position=position)

    raise CommandError(f"unsupported command: {name}")
