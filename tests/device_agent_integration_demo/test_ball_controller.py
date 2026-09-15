from types import SimpleNamespace

import numpy as np
import pytest

from device_agent_integration_demo.ball_controller import BallController
from device_agent_integration_demo.commands import BallPosition, Foot


def make_ball() -> tuple[BallController, SimpleNamespace]:
    data = SimpleNamespace(qpos=np.zeros(30), qvel=np.zeros(30))
    data.qpos[0:7] = [1.0, 2.0, 0.125, 1.0, 0.0, 0.0, 0.0]
    policy = SimpleNamespace(ball_qpos_adr=10, ball_qvel_adr=12, _trunk_qpos_adr=0)
    return BallController(data, policy, seed=7), data


def test_places_ball_at_requested_foot() -> None:
    ball, data = make_ball()
    ball.place(BallPosition.LEFT_KICK)
    np.testing.assert_allclose(data.qpos[10:13], [1.10, 2.055, 0.025])
    ball.place(BallPosition.RIGHT_KICK)
    np.testing.assert_allclose(data.qpos[10:13], [1.10, 1.945, 0.025])


def test_kick_metrics_capture_peak_speed_and_displacement() -> None:
    ball, data = make_ball()
    ball.begin_kick(Foot.LEFT)
    data.qvel[12:15] = [0.4, 0.0, 0.0]
    ball.observe_kick()
    data.qvel[12:15] = 0.0
    data.qpos[10] += 0.1
    result = ball.finish_kick()
    assert result.success
    assert result.max_speed_m_s == 0.4
    assert result.displacement_m == pytest.approx(0.1)


def test_seeded_random_placement_is_reproducible() -> None:
    first, first_data = make_ball()
    second, second_data = make_ball()
    first.place(BallPosition.RANDOM)
    second.place(BallPosition.RANDOM)
    np.testing.assert_allclose(first_data.qpos[10:13], second_data.qpos[10:13])
