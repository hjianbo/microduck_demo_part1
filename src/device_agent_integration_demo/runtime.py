from __future__ import annotations

from typing import Any

from .ball_controller import BallController, KickMetrics
from .commands import BallPosition, Foot


class PolicyRuntime:
    """Small adapter around the pinned upstream PolicyInference object."""

    def __init__(self, policy: Any, data: Any, seed: int | None = None):
        self.policy = policy
        self.ball = BallController(data, policy, seed=seed)

    def set_velocity(self, vx: float, yaw: float) -> None:
        self.policy.set_vel_cmd(vx, 0.0, yaw)

    def place_ball(self, position: BallPosition) -> None:
        self.ball.place(position)

    def start_kick(self, foot: Foot) -> None:
        self.ball.begin_kick(foot)
        # BallController owns placement so that it can measure from the exact
        # initial position. Suppress PolicyInference's second teleport.
        behavior = f"kick_{foot.value}"
        original = self.policy._place_ball
        try:
            self.policy._place_ball = lambda _name: None
            self.policy.trigger_behavior(behavior)
        finally:
            self.policy._place_ball = original

    def kick_in_progress(self) -> bool:
        return self.policy.behavior_mode in {"kick_left", "kick_right"}

    def observe_kick(self) -> None:
        self.ball.observe_kick()

    def finish_kick(self) -> KickMetrics:
        return self.ball.finish_kick()
