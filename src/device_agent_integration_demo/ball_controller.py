from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any

import numpy as np

from .commands import BallPosition, Foot


BALL_RADIUS = 0.025
BALL_OFFSET_X = 0.10
BALL_OFFSET_Y = 0.055


@dataclass(frozen=True)
class KickMetrics:
    success: bool
    displacement_m: float
    max_speed_m_s: float


class BallController:
    """Own deterministic ball placement and kick-result measurement."""

    SUCCESS_DISPLACEMENT_M = 0.08
    SUCCESS_SPEED_M_S = 0.35

    def __init__(self, data: Any, policy: Any, seed: int | None = None):
        if policy.ball_qpos_adr is None or policy.ball_qvel_adr is None:
            raise ValueError("the selected MuJoCo scene has no ball_free joint")
        self.data = data
        self.policy = policy
        self.qpos_adr = int(policy.ball_qpos_adr)
        self.qvel_adr = int(policy.ball_qvel_adr)
        self._random = random.Random(seed)
        self._kick_start: np.ndarray | None = None
        self._kick_max_speed = 0.0

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

    def begin_kick(self, foot: Foot) -> None:
        position = BallPosition.LEFT_KICK if foot == Foot.LEFT else BallPosition.RIGHT_KICK
        self.place(position)
        self._kick_start = self.data.qpos[self.qpos_adr:self.qpos_adr + 2].copy()
        self._kick_max_speed = 0.0

    def observe_kick(self) -> None:
        if self._kick_start is None:
            return
        speed = float(np.linalg.norm(self.data.qvel[self.qvel_adr:self.qvel_adr + 3]))
        self._kick_max_speed = max(self._kick_max_speed, speed)

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
        return metrics
