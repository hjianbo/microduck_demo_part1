from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any, Callable, Protocol

from .commands import (
    DemoCommand,
    Direction,
    KickCommand,
    MoveCommand,
    PlaceBallCommand,
    StopCommand,
    parse_command,
)


class Runtime(Protocol):
    def set_velocity(self, vx: float, yaw: float) -> None: ...
    def place_ball(self, position: Any) -> None: ...
    def start_kick(self, foot: Any) -> None: ...
    def kick_in_progress(self) -> bool: ...
    def observe_kick(self, dt: float) -> None: ...
    def finish_kick(self) -> Any: ...
    def update_ball(self, dt: float) -> bool | None: ...


@dataclass(frozen=True)
class ActionResult:
    code: int
    msg: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionController:
    """Deterministic single-action state machine shared by CLI and MQTT."""

    KICK_SETTLE_S = 0.35
    VELOCITIES = {
        Direction.FORWARD: (0.25, 0.0),
        Direction.LEFT: (0.20, 0.8),
        Direction.RIGHT: (0.20, -0.8),
    }

    def __init__(
        self,
        runtime: Runtime,
        clock: Callable[[], float] = time.monotonic,
        command_timeout_s: float = 1.0,
    ):
        self.runtime = runtime
        self.clock = clock
        self.motion_state = "idle"
        self.vx = 0.0
        self.vy = 0.0
        self.yaw = 0.0
        self.active_action = "none"
        self.kick_side = "none"
        self.ball_state = "ready"
        self.last_action_result = "none"
        self._move_deadline: float | None = None
        self._pending_kick: Any = None
        self._kick_start_at: float | None = None
        self._events: list[dict[str, Any]] = []
        self.command_timeout_s = command_timeout_s

    def submit_payload(self, payload: Any) -> ActionResult:
        return self.submit(parse_command(payload))

    def submit(self, command: DemoCommand) -> ActionResult:
        if isinstance(command, StopCommand):
            if self.active_action == "kick":
                return ActionResult(409, "an active kick cannot be interrupted safely", self.snapshot())
            self._stop("stopped")
            return ActionResult(0, "ok", self.snapshot())

        if self.active_action == "kick":
            return ActionResult(409, "another kick is in progress", self.snapshot())

        if isinstance(command, MoveCommand):
            if command.direction == Direction.BACKWARD:
                self.last_action_result = "rejected"
                self._event("action_failed", action="move", reason="backward_policy_unsupported")
                return ActionResult(422, "backward is unsupported by the pinned walking policy", self.snapshot())
            vx, yaw = self.VELOCITIES[command.direction]
            self.runtime.set_velocity(vx, yaw)
            self.motion_state = "moving"
            self.vx, self.yaw = vx, yaw
            self.active_action = "move"
            self.last_action_result = "none"
            self._move_deadline = self.clock() + command.duration_s
            return ActionResult(0, "accepted", self.snapshot())

        if isinstance(command, PlaceBallCommand):
            if self.motion_state != "idle":
                return ActionResult(409, "ball placement requires an idle robot", self.snapshot())
            self.runtime.place_ball(command.position)
            self.ball_state = "ready"
            self.last_action_result = "success"
            self._event("action_completed", action="place_ball", position=command.position.value)
            return ActionResult(0, "ok", self.snapshot())

        if isinstance(command, KickCommand):
            self.runtime.set_velocity(0.0, 0.0)
            self.motion_state = "idle"
            self.vx = self.yaw = 0.0
            self.active_action = "kick"
            self.kick_side = command.foot.value
            self.ball_state = "ready"
            self.last_action_result = "none"
            self._move_deadline = None
            self._pending_kick = command.foot
            self._kick_start_at = self.clock() + self.KICK_SETTLE_S
            return ActionResult(0, "accepted", self.snapshot())

        raise AssertionError(f"unhandled command: {command!r}")

    def update(self, dt: float = 0.02) -> None:
        # Do not respawn a recently bumped ball while a requested kick is
        # waiting for the robot to settle or while its policy is running.
        settling = None if self.active_action == "kick" else self.runtime.update_ball(dt)
        if settling is True and self.active_action != "kick":
            self.ball_state = "moving"
        elif settling is False:
            self.ball_state = "ready"

        if self._pending_kick is not None:
            assert self._kick_start_at is not None
            if self.clock() < self._kick_start_at:
                return
            self.runtime.start_kick(self._pending_kick)
            self._pending_kick = None
            self._kick_start_at = None
            self.motion_state = "moving"
            return

        if self.active_action == "kick":
            if self.runtime.kick_in_progress():
                self.runtime.observe_kick(dt)
            else:
                metrics = self.runtime.finish_kick()
                self.motion_state = "idle"
                self.active_action = "none"
                # Device Agent only accepts the externally declared ball states.
                # A ball that did not move is still available for another kick,
                # so report it as ready instead of rejecting the whole snapshot
                # with the unsupported legacy value "stopped".
                self.ball_state = "moving" if metrics.max_speed_m_s > 0.05 else "ready"
                self.last_action_result = "success" if metrics.success else "failed"
                event = "action_completed" if metrics.success else "action_failed"
                self._event(
                    event,
                    action="kick",
                    foot=self.kick_side,
                    reason="" if metrics.success else "ball_not_displaced",
                    displacement_m=round(metrics.displacement_m, 4),
                    max_speed_m_s=round(metrics.max_speed_m_s, 4),
                )
            return

        if self._move_deadline is not None and self.clock() >= self._move_deadline:
            self._stop("success")
            self._event("action_completed", action="move")

    def handle_command_timeout(self) -> bool:
        """Stop locomotion after a prolonged MQTT outage."""
        if self.active_action != "move":
            return False
        self._stop("timeout")
        self._event("command_timeout", timeout_s=self.command_timeout_s)
        return True

    def _stop(self, result: str) -> None:
        self.runtime.set_velocity(0.0, 0.0)
        self.motion_state = "idle"
        self.vx = self.yaw = 0.0
        self.active_action = "none"
        self.last_action_result = result
        self._move_deadline = None
        self._pending_kick = None
        self._kick_start_at = None

    def _event(self, event: str, **data: Any) -> None:
        self._events.append({"event": event, **data})

    def drain_events(self) -> list[dict[str, Any]]:
        events, self._events = self._events, []
        return events

    def snapshot(self) -> dict[str, Any]:
        return {
            "motion_state": self.motion_state,
            "vx": self.vx,
            "vy": self.vy,
            "yaw": self.yaw,
            "active_action": self.active_action,
            "kick_side": self.kick_side,
            "ball_state": self.ball_state,
            "last_action_result": self.last_action_result,
            "command_timeout_s": self.command_timeout_s,
        }

    def telemetry_snapshot(self) -> dict[str, str | float]:
        """Return a full snapshot matching every DeviceSpec property."""
        return self.snapshot()
