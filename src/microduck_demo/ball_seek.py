"""Privileged-state ball seeking controller for the MuJoCo demo.

This is deliberately a first-step controller, not a learned vision policy.
It reads the ball free-joint from MuJoCo, hides it outside a simple field of
view, and drives the existing walking and kick policies through their runtime
controls. It validates the seek -> align -> kick loop before adding a camera
or training a high-level policy.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

import numpy as np


class BallSeekController:
    """Find a randomly placed ball, align a foot, and trigger a kick."""

    # Match the upstream BallKick training scene: 70 mm diameter / 15 g ball.
    BALL_RADIUS = 0.035

    SPAWN_RADIUS_MIN = 0.55
    SPAWN_RADIUS_MAX = 1.05

    # A geometric visibility model stands in for a camera in this first step.
    # The controller intentionally does not use the ball bearing while hidden.
    FOV_HALF_ANGLE = math.radians(52.0)
    VISIBILITY_RANGE = 1.35

    # Kick policy expects the ball at the kicking foot, not between the feet.
    KICK_X = 0.09
    KICK_Y = 0.042
    ALIGN_RADIUS = 0.012
    ALIGN_SETTLE_S = 2.0
    NUDGE_S = 1.0
    NUDGE_VX = 0.20
    KICK_X_ERROR_MIN = -0.025
    KICK_X_ERROR_MAX = 0.030
    KICK_Y_ERROR = 0.030

    # The walking policy needs meaningful forward motion to execute a turn;
    # commands near zero settle into standing even with a non-zero yaw target.
    SEARCH_VX = 0.18
    SEARCH_YAW = 0.50
    RESTART_VX = 0.22
    RESTART_DURATION_S = 1.5
    APPROACH_VX_MIN = 0.18
    APPROACH_VX_MAX = 0.25
    APPROACH_YAW_MAX = 1.3
    APPROACH_YAW_GAIN = 2.5

    KICK_SUCCESS_SPEED = 0.35
    KICK_SUCCESS_DISPLACEMENT = 0.06
    BALL_STOP_SPEED = 0.03
    BALL_STOP_SETTLE_S = 0.40
    BALL_STOP_TIMEOUT_S = 10.0
    BALL_SETTLE_DAMPING = 1.5
    BALL_COLORS = (
        ("red", (0.95, 0.12, 0.10, 1.0)),
        ("blue", (0.10, 0.35, 1.00, 1.0)),
        ("yellow", (1.00, 0.85, 0.05, 1.0)),
        ("magenta", (0.90, 0.10, 0.75, 1.0)),
        ("cyan", (0.05, 0.85, 0.90, 1.0)),
        ("green", (0.10, 0.80, 0.20, 1.0)),
    )
    # Match the official browser runtime's 20 control-step post-kick lock.
    # Handing a turning command to the walking policy on the same frame as the
    # kick-policy swap can leave the locomotion policy in a stationary state.
    POST_KICK_RECOVERY_S = 0.40
    STALL_TIMEOUT_S = 2.5
    STALL_RECOVERY_S = 1.0
    STALL_MIN_DISPLACEMENT = 0.025
    STALL_MIN_YAW_CHANGE = math.radians(5.0)
    LOG_PERIOD_S = 0.5

    def __init__(
        self,
        *,
        mujoco: Any,
        model: Any,
        data: Any,
        policy: Any,
        trunk_qpos_adr: int,
        trunk_qvel_adr: int = 0,
        seed: int | None = None,
    ) -> None:
        self.mujoco = mujoco
        self.model = model
        self.data = data
        self.policy = policy
        self.trunk_qpos_adr = int(trunk_qpos_adr)
        self.trunk_qvel_adr = int(trunk_qvel_adr)
        self.ball_qpos_adr = policy.ball_qpos_adr
        self.ball_qvel_adr = policy.ball_qvel_adr
        if self.ball_qpos_adr is None or self.ball_qvel_adr is None:
            raise ValueError("--auto-ball requires a MuJoCo scene with a ball_free joint")

        available = set(policy.behavior_sessions)
        if not ({"kick_left", "kick_right"} & available):
            raise ValueError("--auto-ball requires --kick-left and/or --kick-right")
        self.available_kicks = available

        self.rng = random.Random(seed)
        self.phase = "idle"
        self.foot: str | None = None
        self.align_elapsed = 0.0
        self.nudge_elapsed = 0.0
        self.recovery_elapsed = 0.0
        self.recovery_duration = self.POST_KICK_RECOVERY_S
        self.stall_elapsed = 0.0
        self.progress_start_pose: tuple[float, float, float] | None = None
        self.restart_elapsed = 0.0
        self.ball_stop_elapsed = 0.0
        self.ball_wait_elapsed = 0.0
        self.kick_ball_start = np.zeros(2, dtype=np.float32)
        self.kick_max_speed = 0.0
        self.last_log_at = 0.0
        self.episode = 0
        self.successes = 0
        # A left kick hands back more reliably into a clockwise (negative yaw)
        # walking command. A full curved sweep still scans the whole arena.
        self.search_direction = -1.0
        self.ball_color_index = -1
        self.ball_color_name = "original"
        try:
            self.ball_geom_id = int(
                self.mujoco.mj_name2id(
                    self.model, self.mujoco.mjtObj.mjOBJ_GEOM, "ball_geom"
                )
            )
        except (AttributeError, TypeError):
            self.ball_geom_id = -1

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _robot_pose(self) -> tuple[float, float, float]:
        q = self.data.qpos
        a = self.trunk_qpos_adr
        qw, qx, qy, qz = (float(q[a + i]) for i in range(3, 7))
        yaw = math.atan2(
            2.0 * (qw * qz + qx * qy),
            1.0 - 2.0 * (qy * qy + qz * qz),
        )
        return float(q[a]), float(q[a + 1]), yaw

    def _ball_position(self) -> np.ndarray:
        a = self.ball_qpos_adr
        return np.asarray(self.data.qpos[a : a + 2], dtype=np.float32)

    def _ball_velocity(self) -> float:
        a = self.ball_qvel_adr
        return float(math.hypot(float(self.data.qvel[a]), float(self.data.qvel[a + 1])))

    def _relative_ball(self) -> tuple[float, float, float, float]:
        rx, ry, yaw = self._robot_pose()
        bx, by = self._ball_position()
        dx, dy = float(bx) - rx, float(by) - ry
        c, s = math.cos(yaw), math.sin(yaw)
        # World -> robot yaw frame: +x forward, +y left.
        x_rel = c * dx + s * dy
        y_rel = -s * dx + c * dy
        distance = math.hypot(x_rel, y_rel)
        bearing = math.atan2(y_rel, x_rel)
        return x_rel, y_rel, distance, bearing

    def _visible(self, distance: float, bearing: float) -> bool:
        return distance <= self.VISIBILITY_RANGE and abs(bearing) <= self.FOV_HALF_ANGLE

    def _set_velocity(self, vx: float, yaw: float) -> None:
        """Update the walking command without printing at 50 Hz."""
        self.policy.vel_cmd[:] = (vx, 0.0, yaw)
        self.policy._update_policy_session()
        self.policy._update_command()

    def _advance_ball_color(self) -> None:
        self.ball_color_index = (self.ball_color_index + 1) % len(self.BALL_COLORS)
        self.ball_color_name, rgba = self.BALL_COLORS[self.ball_color_index]
        if self.ball_geom_id >= 0:
            self.model.geom_rgba[self.ball_geom_id] = rgba

    def _place_random_ball(self) -> None:
        self._advance_ball_color()
        angle = self.rng.uniform(-math.pi, math.pi)
        radius = math.sqrt(
            self.rng.uniform(self.SPAWN_RADIUS_MIN**2, self.SPAWN_RADIUS_MAX**2)
        )
        rx, ry, _yaw = self._robot_pose()
        bx = rx + radius * math.cos(angle)
        by = ry + radius * math.sin(angle)
        a = self.ball_qpos_adr
        v = self.ball_qvel_adr
        self.data.qpos[a : a + 7] = (bx, by, self.BALL_RADIUS, 1.0, 0.0, 0.0, 0.0)
        self.data.qvel[v : v + 6] = 0.0
        self.mujoco.mj_forward(self.model, self.data)

    def _announce_episode(self) -> None:
        x, y, distance, bearing = self._relative_ball()
        print(
            f"AUTO-BALL: episode {self.episode} | ball rel="
            f"({x:+.2f}, {y:+.2f}) m distance={distance:.2f} m "
            f"bearing={math.degrees(bearing):+.0f}° color={self.ball_color_name}"
        )

    def start(self) -> None:
        self._place_random_ball()
        self.phase = "search"
        self.foot = None
        self.align_elapsed = 0.0
        self.nudge_elapsed = 0.0
        self.recovery_elapsed = 0.0
        self.restart_elapsed = 0.0
        self.progress_start_pose = None
        self.search_direction = -1.0
        self.episode += 1
        self._announce_episode()

    def _choose_foot(self, _y_rel: float) -> str:
        # The shipped left kick is verified end-to-end in this desktop scene.
        # Keep right as a fallback for installations that only provide it.
        return "left" if "kick_left" in self.available_kicks else "right"

    def _trigger_kick(self) -> None:
        assert self.foot in ("left", "right")
        kick_name = f"kick_{self.foot}"
        self.kick_ball_start[:] = self._ball_position()
        self.kick_max_speed = 0.0
        # place_ball=False keeps the ball at the pose reached by the controller.
        self.policy.trigger_behavior(kick_name, place_ball=False)
        self.phase = "kick"
        print(f"AUTO-BALL: aligned -> {kick_name}")

    def _finish_kick(self) -> None:
        displacement = float(np.linalg.norm(self._ball_position() - self.kick_ball_start))
        success = (
            self.kick_max_speed >= self.KICK_SUCCESS_SPEED
            or displacement >= self.KICK_SUCCESS_DISPLACEMENT
        )
        if success:
            self.successes += 1
        print(
            f"AUTO-BALL: kick {'SUCCESS' if success else 'miss'} | "
            f"max_ball_speed={self.kick_max_speed:.2f} m/s "
            f"displacement={displacement:.2f} m "
            f"successes={self.successes}"
        )
        # Keep the kicked ball in the scene until it has visibly settled. The
        # next episode is spawned only after a continuous low-speed window.
        self.phase = "wait_ball_stop"
        self.ball_stop_elapsed = 0.0
        self.ball_wait_elapsed = 0.0
        self.stall_elapsed = 0.0
        self.progress_start_pose = None
        self._set_velocity(0.0, 0.0)
        self.foot = None
        self.align_elapsed = 0.0
        self.nudge_elapsed = 0.0
        print("AUTO-BALL: waiting for old ball to stop before respawn")

    def _spawn_next_episode(self, *, timed_out: bool) -> None:
        if timed_out:
            print("AUTO-BALL: ball-stop timeout -> respawn")
        else:
            print("AUTO-BALL: old ball stopped -> respawn")
        self._place_random_ball()
        # Keep the browser-compatible post-kick zero-command grace after the
        # replacement appears, then resume searching.
        self.phase = "recover"
        self.recovery_elapsed = 0.0
        self.recovery_duration = self.POST_KICK_RECOVERY_S
        self.restart_elapsed = 0.0
        self.progress_start_pose = None
        self.episode += 1
        self._announce_episode()

    def _watch_for_stall(self, dt: float) -> bool:
        """Recover when commanded locomotion makes no net pose progress."""
        pose = self._robot_pose()
        if self.progress_start_pose is None:
            self.progress_start_pose = pose
        self.stall_elapsed += max(0.0, dt)
        if self.stall_elapsed < self.STALL_TIMEOUT_S:
            return False

        sx, sy, syaw = self.progress_start_pose
        x, y, yaw = pose
        displacement = math.hypot(x - sx, y - sy)
        yaw_change = abs(math.atan2(math.sin(yaw - syaw), math.cos(yaw - syaw)))
        self.progress_start_pose = pose
        self.stall_elapsed = 0.0
        if (
            displacement >= self.STALL_MIN_DISPLACEMENT
            or yaw_change >= self.STALL_MIN_YAW_CHANGE
        ):
            return False

        self.phase = "recover"
        self.recovery_elapsed = 0.0
        self.recovery_duration = self.STALL_RECOVERY_S
        self.restart_elapsed = 0.0
        self.progress_start_pose = None
        self.search_direction = -1.0
        self._set_velocity(0.0, 0.0)
        # A stalled gait can retain an action-history fixed point. This is the
        # same history reset used by the official runtime's recovery path.
        if hasattr(self.policy, "last_action"):
            self.policy.last_action.fill(0.0)
        print("AUTO-BALL: locomotion stalled -> reset gait and restart")
        return True

    def update(self, dt: float) -> None:
        """Advance search/approach/alignment at the control-loop rate."""
        if self.phase == "idle":
            return

        if self.policy.behavior_mode is not None:
            if self.phase == "kick":
                self.kick_max_speed = max(self.kick_max_speed, self._ball_velocity())
            return

        if self.phase == "kick":
            self._finish_kick()
            return

        if self.phase == "wait_ball_stop":
            self._set_velocity(0.0, 0.0)
            step_dt = max(0.0, dt)
            self.ball_wait_elapsed += step_dt
            # The training ball has almost no rolling resistance and can keep
            # creeping indefinitely. Apply smooth damping only after the kick
            # has been measured so the old ball visibly rolls, then settles.
            damping = math.exp(-self.BALL_SETTLE_DAMPING * step_dt)
            v = self.ball_qvel_adr
            self.data.qvel[v : v + 6] *= damping
            speed = self._ball_velocity()
            if speed <= self.BALL_STOP_SPEED:
                self.ball_stop_elapsed += step_dt
            else:
                self.ball_stop_elapsed = 0.0
            stopped = self.ball_stop_elapsed >= self.BALL_STOP_SETTLE_S
            timed_out = self.ball_wait_elapsed >= self.BALL_STOP_TIMEOUT_S
            if stopped or timed_out:
                self._spawn_next_episode(timed_out=timed_out and not stopped)
            else:
                now = time.monotonic()
                if now - self.last_log_at >= self.LOG_PERIOD_S:
                    self.last_log_at = now
                    print(
                        "AUTO-BALL: waiting for old ball | "
                        f"speed={speed:.2f} m/s "
                        f"settled={self.ball_stop_elapsed:.2f}/"
                        f"{self.BALL_STOP_SETTLE_S:.2f}s"
                    )
            return

        if self.phase == "recover":
            self._set_velocity(0.0, 0.0)
            self.recovery_elapsed += max(0.0, dt)
            if self.recovery_elapsed >= self.recovery_duration:
                self.phase = "restart"
                self.restart_elapsed = 0.0
                self.progress_start_pose = None
                print("AUTO-BALL: recovery done -> straight walking restart")
            return

        if self.phase == "restart":
            self._set_velocity(self.RESTART_VX, 0.0)
            self.restart_elapsed += max(0.0, dt)
            if self._watch_for_stall(dt):
                return
            if self.restart_elapsed >= self.RESTART_DURATION_S:
                self.phase = "search"
                self.stall_elapsed = 0.0
                self.progress_start_pose = None
                print("AUTO-BALL: walking restarted -> search")
            return

        x_rel, y_rel, distance, bearing = self._relative_ball()
        visible = self._visible(distance, bearing)

        # Losing the target is a real camera event in this first-step model.
        # Drop the selected foot and return to a blind search instead of using
        # the hidden MuJoCo bearing to keep steering toward the ball.
        if self.phase in {"approach", "align", "nudge"} and not visible:
            self.phase = "search"
            self.foot = None
            self.align_elapsed = 0.0
            self.nudge_elapsed = 0.0

        if self.phase == "search" and visible:
            self.foot = self._choose_foot(y_rel)
            self.phase = "approach"
            print(
                f"AUTO-BALL: ball found -> approach with {self.foot} foot "
                f"(distance={distance:.2f} m)"
            )

        if self.phase == "search":
            # Deliberately ignore the hidden ball's bearing: this simulates a
            # camera search rather than cheating with the MuJoCo position.
            # Forward motion is required because the walking policy cannot
            # reliably turn in place. A steady curved path scans through a
            # complete 360 degrees.
            self._set_velocity(self.SEARCH_VX, self.search_direction * self.SEARCH_YAW)
        elif self.phase == "nudge":
            self.nudge_elapsed += max(0.0, dt)
            self._set_velocity(self.NUDGE_VX, 0.0)
            if self.nudge_elapsed >= self.NUDGE_S:
                self.phase = "align"
                self.align_elapsed = 0.0
                self._set_velocity(0.0, 0.0)
        elif self.phase == "align":
            # Latch the stop instead of immediately returning to approach as
            # the last walking step coasts. The kick network was trained from
            # a stationary pose and misses reliably when triggered mid-gait.
            self._set_velocity(0.0, 0.0)
            self.align_elapsed += max(0.0, dt)
            side = 1.0 if self.foot == "left" else -1.0
            ex = x_rel - self.KICK_X
            ey = y_rel - side * self.KICK_Y
            if self.align_elapsed >= self.ALIGN_SETTLE_S:
                in_kick_window = (
                    self.KICK_X_ERROR_MIN <= ex <= self.KICK_X_ERROR_MAX
                    and abs(ey) <= self.KICK_Y_ERROR
                )
                if in_kick_window:
                    self._trigger_kick()
                    return
                self.align_elapsed = 0.0
                if ex > self.KICK_X_ERROR_MAX and abs(ey) <= self.KICK_Y_ERROR:
                    self.phase = "nudge"
                    self.nudge_elapsed = 0.0
                    print(
                        "AUTO-BALL: settled short -> forward nudge "
                        f"(error=({ex:+.3f},{ey:+.3f}) m)"
                    )
                else:
                    self.phase = "approach"
                    print(
                        "AUTO-BALL: settled outside kick window -> realign "
                        f"(error=({ex:+.3f},{ey:+.3f}) m)"
                    )
        else:
            side = 1.0 if self.foot == "left" else -1.0
            ex = x_rel - self.KICK_X
            ey = y_rel - side * self.KICK_Y
            target_distance = math.hypot(ex, ey)
            target_bearing = math.atan2(ey, ex)

            if target_distance <= self.ALIGN_RADIUS:
                self.phase = "align"
                self.align_elapsed = 0.0
                self._set_velocity(0.0, 0.0)
            else:
                forward_alignment = max(0.15, math.cos(target_bearing))
                speed_scale = min(1.0, max(0.25, target_distance / 0.5))
                vx = self._clip(
                    self.APPROACH_VX_MAX * forward_alignment * speed_scale,
                    self.APPROACH_VX_MIN,
                    self.APPROACH_VX_MAX,
                )
                yaw = self._clip(
                    self.APPROACH_YAW_GAIN * target_bearing,
                    -self.APPROACH_YAW_MAX,
                    self.APPROACH_YAW_MAX,
                )
                self._set_velocity(vx, yaw)

        if self.phase in {"search", "approach", "nudge"}:
            self._watch_for_stall(dt)

        now = time.monotonic()
        if now - self.last_log_at >= self.LOG_PERIOD_S:
            self.last_log_at = now
            print(
                f"AUTO-BALL: {self.phase} | visible={visible} "
                f"rel=({x_rel:+.2f},{y_rel:+.2f}) "
                f"d={distance:.2f} bearing={math.degrees(bearing):+.0f}°"
            )
