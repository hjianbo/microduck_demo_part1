import math

import numpy as np

from microduck_demo.ball_seek import BallSeekController


class FakeMujoco:
    class mjtObj:
        mjOBJ_GEOM = 5

    def __init__(self) -> None:
        self.forward_calls = 0

    def mj_name2id(self, model: object, object_type: int, name: str) -> int:
        assert object_type == self.mjtObj.mjOBJ_GEOM
        return 0 if name == "ball_geom" else -1

    def mj_forward(self, model: object, data: object) -> None:
        self.forward_calls += 1


class FakeData:
    def __init__(self) -> None:
        self.qpos = np.zeros(32, dtype=np.float64)
        self.qvel = np.zeros(32, dtype=np.float64)
        # Robot free joint starts at qpos 0 with an identity quaternion.
        self.qpos[3] = 1.0


class FakeModel:
    def __init__(self) -> None:
        self.geom_rgba = np.zeros((1, 4), dtype=np.float32)


class FakePolicy:
    ball_qpos_adr = 10
    ball_qvel_adr = 12

    def __init__(self) -> None:
        self.behavior_sessions = {"kick_left": object(), "kick_right": object()}
        self.behavior_mode = None
        self.vel_cmd = np.zeros(3, dtype=np.float32)
        self.triggers: list[tuple[str, bool]] = []

    def _update_policy_session(self) -> None:
        pass

    def _update_command(self) -> None:
        pass

    def trigger_behavior(self, name: str, place_ball: bool = True) -> None:
        self.triggers.append((name, place_ball))
        self.behavior_mode = name


def make_controller(seed: int = 7):
    mujoco = FakeMujoco()
    data = FakeData()
    policy = FakePolicy()
    controller = BallSeekController(
        mujoco=mujoco,
        model=FakeModel(),
        data=data,
        policy=policy,
        trunk_qpos_adr=0,
        trunk_qvel_adr=0,
        seed=seed,
    )
    return controller, mujoco, data, policy


def set_ball(data: FakeData, x: float, y: float) -> None:
    data.qpos[10:17] = (x, y, BallSeekController.BALL_RADIUS, 1.0, 0.0, 0.0, 0.0)


def test_start_places_a_valid_random_ball() -> None:
    controller, mujoco, data, _policy = make_controller()
    data.qpos[0:2] = (2.0, -1.0)

    controller.start()

    distance = math.hypot(data.qpos[10] - 2.0, data.qpos[11] + 1.0)
    assert controller.phase == "search"
    assert controller.episode == 1
    assert controller.SPAWN_RADIUS_MIN <= distance <= controller.SPAWN_RADIUS_MAX
    assert data.qpos[12] == controller.BALL_RADIUS
    assert mujoco.forward_calls == 1
    assert controller.ball_color_name == "red"
    np.testing.assert_allclose(controller.model.geom_rgba[0], controller.BALL_COLORS[0][1])


def test_hidden_ball_uses_blind_search_command() -> None:
    controller, _mujoco, data, policy = make_controller()
    controller.phase = "search"
    # Directly behind the robot, hence outside the geometric camera FOV.
    set_ball(data, -0.8, 0.0)

    controller.update(0.02)

    np.testing.assert_allclose(
        policy.vel_cmd,
        (controller.SEARCH_VX, 0.0, -controller.SEARCH_YAW),
    )
    assert controller.phase == "search"
    assert controller.foot is None


def test_aligned_ball_triggers_kick_without_teleporting_it() -> None:
    controller, _mujoco, data, policy = make_controller()
    controller.phase = "search"
    set_ball(data, controller.KICK_X, controller.KICK_Y)

    controller.update(0.02)
    controller.update(controller.ALIGN_SETTLE_S)

    assert controller.phase == "kick"
    assert policy.triggers == [("kick_left", False)]
    np.testing.assert_allclose(data.qpos[10:12], (controller.KICK_X, controller.KICK_Y))


def test_lost_target_returns_to_search() -> None:
    controller, _mujoco, data, policy = make_controller()
    controller.phase = "approach"
    controller.foot = "left"
    set_ball(data, -0.8, 0.0)

    controller.update(0.02)

    assert controller.phase == "search"
    assert controller.foot is None
    np.testing.assert_allclose(
        policy.vel_cmd,
        (controller.SEARCH_VX, 0.0, -controller.SEARCH_YAW),
    )


def test_kick_waits_for_old_ball_to_stop_then_respawns_with_new_color() -> None:
    controller, _mujoco, data, policy = make_controller()
    controller.start()
    controller.phase = "kick"
    set_ball(data, controller.KICK_X, controller.KICK_Y)
    controller.kick_ball_start[:] = data.qpos[10:12]

    controller.update(0.02)

    assert controller.phase == "wait_ball_stop"
    assert controller.episode == 1
    np.testing.assert_allclose(policy.vel_cmd, (0.0, 0.0, 0.0))

    old_position = data.qpos[10:12].copy()
    data.qvel[12] = 0.2
    controller.update(1.0)
    assert controller.phase == "wait_ball_stop"
    assert controller.episode == 1
    np.testing.assert_allclose(data.qpos[10:12], old_position)

    data.qvel[12] = 0.0
    controller.update(controller.BALL_STOP_SETTLE_S)
    assert controller.phase == "recover"
    assert controller.episode == 2
    assert controller.ball_color_name == "blue"

    controller.update(controller.POST_KICK_RECOVERY_S)
    assert controller.phase == "restart"
    np.testing.assert_allclose(policy.vel_cmd, (0.0, 0.0, 0.0))

    controller.update(controller.RESTART_DURATION_S)
    assert controller.phase == "search"
    np.testing.assert_allclose(
        policy.vel_cmd,
        (controller.RESTART_VX, 0.0, 0.0),
    )

    controller.update(0.02)
    np.testing.assert_allclose(
        policy.vel_cmd,
        (controller.SEARCH_VX, 0.0, -controller.SEARCH_YAW),
    )


def test_stalled_search_resets_action_history_and_recovers() -> None:
    controller, _mujoco, data, policy = make_controller()
    policy.last_action = np.ones(14, dtype=np.float32)
    controller.phase = "search"
    set_ball(data, -0.8, 0.0)

    controller.update(controller.STALL_TIMEOUT_S)

    assert controller.phase == "recover"
    assert controller.search_direction == -1.0
    np.testing.assert_allclose(policy.vel_cmd, (0.0, 0.0, 0.0))
    np.testing.assert_allclose(policy.last_action, 0.0)
