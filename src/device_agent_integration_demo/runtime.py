from __future__ import annotations

from typing import Any

from .ball_controller import BallController, KickMetrics
from .commands import BallPosition, Foot


class PolicyRuntime:
    """Small adapter around the pinned upstream PolicyInference object."""

    def __init__(
        self,
        policy: Any,
        data: Any,
        seed: int | None = None,
        ball_velocity_damping: float = 3.0,
    ):
        self.policy = policy
        self.ball = BallController(
            data, policy, seed=seed, velocity_damping=ball_velocity_damping
        )

    def set_velocity(self, vx: float, yaw: float) -> None:
        self.policy.set_vel_cmd(vx, 0.0, yaw)

    def place_ball(self, position: BallPosition) -> None:
        self.ball.place(position)

    def start_kick(self, foot: Foot) -> None:
        self.ball.begin_kick()
        # Upstream's interactive kick helper teleports the ball into the
        # policy's training window. Suppress that behavior: this demo must kick
        # the ball wherever the user has moved the robot relative to it.
        behavior = f"kick_{foot.value}"
        original = self.policy._place_ball
        try:
            self.policy._place_ball = lambda _name: None
            self.policy.trigger_behavior(behavior)
        finally:
            self.policy._place_ball = original

    def kick_in_progress(self) -> bool:
        return self.policy.behavior_mode in {"kick_left", "kick_right"}

    def observe_kick(self, dt: float) -> None:
        self.ball.observe_kick(dt)

    def finish_kick(self) -> KickMetrics:
        return self.ball.finish_kick()

    def update_ball(self, dt: float) -> bool | None:
        return self.ball.update_settling(dt)
