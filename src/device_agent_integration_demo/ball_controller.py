from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any

import numpy as np

from .commands import BallPosition


BALL_RADIUS = 0.035
BALL_OFFSET_X = 0.09
BALL_OFFSET_Y = 0.042
DEMO_SPAWN_FORWARD_M = 0.43
BALL_COLORS = (
    ("orange", (1.0, 0.55, 0.0, 1.0)),
    ("blue", (0.10, 0.35, 1.0, 1.0)),
    ("yellow", (1.0, 0.85, 0.05, 1.0)),
    ("magenta", (0.90, 0.10, 0.75, 1.0)),
    ("cyan", (0.05, 0.85, 0.90, 1.0)),
    ("green", (0.10, 0.80, 0.20, 1.0)),
)


@dataclass(frozen=True)
class KickMetrics:
    success: bool
    displacement_m: float
    max_speed_m_s: float


class BallController:
    """Own deterministic ball placement and kick-result measurement."""

    SUCCESS_DISPLACEMENT_M = 0.08
    SUCCESS_SPEED_M_S = 0.35
    MOVEMENT_DISPLACEMENT_M = 0.025
    MOVEMENT_SPEED_M_S = 0.08
    STOP_SPEED_M_S = 0.03

    def __init__(
        self,
        data: Any,
        policy: Any,
        seed: int | None = None,
        velocity_damping: float = 3.0,
        model: Any | None = None,
        ball_geom_id: int = -1,
    ):
        if policy.ball_qpos_adr is None or policy.ball_qvel_adr is None:
            raise ValueError("the selected MuJoCo scene has no ball_free joint")
        self.data = data
        self.policy = policy
        self.model = model
        self.ball_geom_id = ball_geom_id
        self.qpos_adr = int(policy.ball_qpos_adr)
        self.qvel_adr = int(policy.ball_qvel_adr)
        self._random = random.Random(seed)
        self.velocity_damping = velocity_damping
        self._kick_start: np.ndarray | None = None
        self._kick_max_speed = 0.0
        self._damping_active = False
        self._settling = False
        self._tracked_position: np.ndarray | None = None
        self._color_index = -1
        self.color = "unknown"

    def _trunk_pose(self) -> tuple[float, float, float]:
        adr = int(self.policy._trunk_qpos_adr)
        x, y = (float(v) for v in self.data.qpos[adr:adr + 2])
        qw, qx, qy, qz = (float(v) for v in self.data.qpos[adr + 3:adr + 7])
        yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
        return x, y, yaw

    def _set_relative(self, forward: float, lateral: float) -> None:
        x, y, yaw = self._trunk_pose()
        bx = x + math.cos(yaw) * forward - math.sin(yaw) * lateral
        by = y + math.sin(yaw) * forward + math.cos(yaw) * lateral
        self.data.qpos[self.qpos_adr:self.qpos_adr + 7] = [bx, by, BALL_RADIUS, 1, 0, 0, 0]
        self.data.qvel[self.qvel_adr:self.qvel_adr + 6] = 0.0
        self._tracked_position = self.data.qpos[self.qpos_adr:self.qpos_adr + 2].copy()
        self._damping_active = False
        self._settling = False

    def place(self, position: BallPosition) -> None:
        if position == BallPosition.LEFT_KICK:
            self._set_relative(BALL_OFFSET_X, BALL_OFFSET_Y)
        elif position == BallPosition.RIGHT_KICK:
            self._set_relative(BALL_OFFSET_X, -BALL_OFFSET_Y)
        elif position == BallPosition.RANDOM:
            distance = self._random.uniform(0.18, 0.45)
            angle = self._random.uniform(-0.75, 0.75)
            self._set_relative(distance * math.cos(angle), distance * math.sin(angle))
        else:
            self._set_relative(0.30, 0.0)

    def spawn_next_demo_ball(self) -> None:
        """Spawn the next colored ball at the calibrated five-second approach."""
        self._color_index = (self._color_index + 1) % len(BALL_COLORS)
        self.color, rgba = BALL_COLORS[self._color_index]
        if self.model is not None and self.ball_geom_id >= 0:
            self.model.geom_rgba[self.ball_geom_id] = rgba
        self._set_relative(DEMO_SPAWN_FORWARD_M, 0.0)
        print(
            f"Ball respawned: color={self.color}, "
            f"forward={DEMO_SPAWN_FORWARD_M:.2f} m "
            "(approach with: move forward --duration 5)"
        )

    def begin_kick(self) -> None:
        """Measure a kick from the ball's current position without moving it."""
        self._kick_start = self.data.qpos[self.qpos_adr:self.qpos_adr + 2].copy()
        self._kick_max_speed = 0.0
        self._damping_active = False
        self._settling = False

    def observe_kick(self, dt: float) -> None:
        if self._kick_start is None:
            return
        speed = float(np.linalg.norm(self.data.qvel[self.qvel_adr:self.qvel_adr + 3]))
        self._kick_max_speed = max(self._kick_max_speed, speed)
        if speed >= 0.10:
            self._damping_active = True
        if self._damping_active:
            self._apply_velocity_damping(dt)

    def finish_kick(self) -> KickMetrics:
        if self._kick_start is None:
            raise RuntimeError("no kick measurement is active")
        current = self.data.qpos[self.qpos_adr:self.qpos_adr + 2]
        displacement = float(np.linalg.norm(current - self._kick_start))
        metrics = KickMetrics(
            success=(self._kick_max_speed >= self.SUCCESS_SPEED_M_S or displacement >= self.SUCCESS_DISPLACEMENT_M),
            displacement_m=displacement,
            max_speed_m_s=self._kick_max_speed,
        )
        self._kick_start = None
        self._settling = self._damping_active
        return metrics

    def update_settling(self, dt: float) -> bool | None:
        """Track any displaced ball, damp it, and respawn it after it stops."""
        # Kick observation owns damping and measurements while it is active.
        if self._kick_start is not None:
            return None
        position = self.data.qpos[self.qpos_adr:self.qpos_adr + 2]
        planar_velocity = self.data.qvel[self.qvel_adr:self.qvel_adr + 2]
        speed = float(np.linalg.norm(planar_velocity))
        displacement = (
            0.0
            if self._tracked_position is None
            else float(np.linalg.norm(position - self._tracked_position))
        )
        if not self._settling and (
            speed >= self.MOVEMENT_SPEED_M_S
            or displacement >= self.MOVEMENT_DISPLACEMENT_M
        ):
            self._damping_active = True
            self._settling = True

        if not self._settling:
            return None
        self._apply_velocity_damping(dt)
        speed = float(np.linalg.norm(self.data.qvel[self.qvel_adr:self.qvel_adr + 2]))
        if speed <= self.STOP_SPEED_M_S:
            self.data.qvel[self.qvel_adr:self.qvel_adr + 6] = 0.0
            self._settling = False
            self._damping_active = False
            self.spawn_next_demo_ball()
            return False
        return True

    def _apply_velocity_damping(self, dt: float) -> None:
        factor = math.exp(-self.velocity_damping * max(0.0, dt))
        self.data.qvel[self.qvel_adr:self.qvel_adr + 6] *= factor
