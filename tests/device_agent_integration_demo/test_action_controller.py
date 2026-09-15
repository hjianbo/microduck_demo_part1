from dataclasses import dataclass

from device_agent_integration_demo.action_controller import ActionController
from device_agent_integration_demo.ball_controller import KickMetrics
from device_agent_integration_demo.commands import (
    BallPosition,
    Direction,
    Foot,
    KickCommand,
    MoveCommand,
    PlaceBallCommand,
    StopCommand,
)


class Clock:
    now = 10.0

    def __call__(self) -> float:
        return self.now


@dataclass
class FakeRuntime:
    velocities: list[tuple[float, float]] = None
    kicking: bool = False
    kick_foot: Foot | None = None
    observations: int = 0

    def __post_init__(self) -> None:
        self.velocities = []

    def set_velocity(self, vx: float, yaw: float) -> None:
        self.velocities.append((vx, yaw))

    def place_ball(self, position: object) -> None:
        self.position = position

    def start_kick(self, foot: Foot) -> None:
        self.kicking = True
        self.kick_foot = foot

    def kick_in_progress(self) -> bool:
        return self.kicking

    def observe_kick(self) -> None:
        self.observations += 1

    def finish_kick(self) -> KickMetrics:
        return KickMetrics(True, 0.12, 0.8)


def test_move_maps_to_verified_velocity_and_stops_at_deadline() -> None:
    runtime, clock = FakeRuntime(), Clock()
    controller = ActionController(runtime, clock)
    result = controller.submit(MoveCommand(Direction.LEFT, 1.5))
    assert result.code == 0
    assert runtime.velocities == [(0.2, 0.8)]
    assert controller.snapshot()["motion_state"] == "turning_left"

    clock.now += 1.49
    controller.update()
    assert runtime.velocities == [(0.2, 0.8)]
    clock.now += 0.01
    controller.update()
    assert runtime.velocities[-1] == (0.0, 0.0)
    assert controller.snapshot()["motion_state"] == "idle"
    assert controller.drain_events() == [{"event": "action_completed", "action": "move"}]


def test_backward_is_explicitly_unsupported() -> None:
    controller = ActionController(FakeRuntime())
    result = controller.submit(MoveCommand(Direction.BACKWARD))
    assert result.code == 422
    assert result.data["last_action_result"] == "rejected"
    assert controller.drain_events()[0]["reason"] == "backward_policy_unsupported"


def test_stop_cancels_bounded_move() -> None:
    runtime, clock = FakeRuntime(), Clock()
    controller = ActionController(runtime, clock)
    controller.submit(MoveCommand(Direction.FORWARD, 1.0))
    result = controller.submit(StopCommand())
    clock.now += 2
    controller.update()
    assert result.code == 0
    assert runtime.velocities[-1] == (0.0, 0.0)
    assert controller.snapshot()["motion_state"] == "idle"


def test_ball_maintenance_requires_idle_robot() -> None:
    runtime = FakeRuntime()
    controller = ActionController(runtime)
    controller.submit(MoveCommand(Direction.FORWARD))
    result = controller.submit(PlaceBallCommand(BallPosition.RANDOM))
    assert result.code == 409
    assert not hasattr(runtime, "position")


def test_kick_is_exclusive_and_reports_metrics() -> None:
    runtime, clock = FakeRuntime(), Clock()
    controller = ActionController(runtime, clock)
    assert controller.submit(KickCommand(Foot.RIGHT)).code == 0
    assert runtime.velocities == [(0.0, 0.0)]
    assert runtime.kick_foot is None
    assert controller.snapshot()["motion_state"] == "stopping"
    assert controller.submit(KickCommand(Foot.LEFT)).code == 409

    clock.now += controller.KICK_SETTLE_S
    controller.update()
    assert runtime.kick_foot == Foot.RIGHT
    assert controller.submit(KickCommand(Foot.LEFT)).code == 409
    assert controller.submit(StopCommand()).code == 409

    controller.update()
    assert runtime.observations == 1
    runtime.kicking = False
    controller.update()
    assert controller.snapshot()["last_action_result"] == "success"
    assert controller.drain_events() == [{
        "event": "action_completed",
        "action": "kick",
        "foot": "right",
        "reason": "",
        "displacement_m": 0.12,
        "max_speed_m_s": 0.8,
    }]
