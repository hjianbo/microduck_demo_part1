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
    ball_updates: int = 0

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

    def observe_kick(self, dt: float) -> None:
        self.observations += 1

    def finish_kick(self) -> KickMetrics:
        return KickMetrics(True, 0.12, 0.8)

    def update_ball(self, dt: float) -> bool | None:
        self.ball_updates += 1
        return None


def test_move_maps_to_verified_velocity_and_stops_at_deadline() -> None:
    runtime, clock = FakeRuntime(), Clock()
    controller = ActionController(runtime, clock)
    result = controller.submit(MoveCommand(Direction.LEFT, 1.5))
    assert result.code == 0
    assert runtime.velocities == [(0.2, 0.8)]
    assert controller.snapshot()["motion_state"] == "moving"
    assert controller.snapshot()["vx"] == 0.2
    assert controller.snapshot()["vy"] == 0.0

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


def test_mqtt_timeout_stops_only_active_locomotion() -> None:
    runtime = FakeRuntime()
    controller = ActionController(runtime, command_timeout_s=1.5)
    assert controller.handle_command_timeout() is False

    controller.submit(MoveCommand(Direction.FORWARD, 5.0))
    assert controller.handle_command_timeout() is True

    assert runtime.velocities[-1] == (0.0, 0.0)
    assert controller.snapshot()["last_action_result"] == "timeout"
    assert controller.snapshot()["command_timeout_s"] == 1.5
    assert controller.drain_events() == [{"event": "command_timeout", "timeout_s": 1.5}]


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
    assert controller.snapshot()["motion_state"] == "idle"
    assert controller.submit(KickCommand(Foot.LEFT)).code == 409

    controller.update()
    assert runtime.ball_updates == 0

    clock.now += controller.KICK_SETTLE_S
    controller.update()
    assert runtime.kick_foot == Foot.RIGHT
    assert controller.snapshot()["motion_state"] == "moving"
    assert controller.submit(KickCommand(Foot.LEFT)).code == 409
    assert controller.submit(StopCommand()).code == 409

    controller.update()
    assert runtime.observations == 1
    runtime.kicking = False
    controller.update()
    assert controller.snapshot()["last_action_result"] == "success"
    assert controller.snapshot()["motion_state"] == "idle"
    assert controller.drain_events() == [{
        "event": "action_completed",
        "action": "kick",
        "foot": "right",
        "reason": "",
        "displacement_m": 0.12,
        "max_speed_m_s": 0.8,
    }]


def test_snapshots_only_expose_device_agent_motion_states() -> None:
    runtime, clock = FakeRuntime(), Clock()
    controller = ActionController(runtime, clock)

    snapshots = [controller.snapshot()]
    for direction in (Direction.FORWARD, Direction.LEFT, Direction.RIGHT):
        snapshots.append(controller.submit(MoveCommand(direction)).data)
        snapshots.append(controller.submit(StopCommand()).data)
    snapshots.append(controller.submit(KickCommand(Foot.LEFT)).data)
    clock.now += controller.KICK_SETTLE_S
    controller.update()
    snapshots.append(controller.snapshot())
    runtime.kicking = False
    controller.update()
    snapshots.append(controller.snapshot())

    assert {state["motion_state"] for state in snapshots} <= {"idle", "moving"}
    assert all(state["vy"] == 0.0 for state in snapshots)


def test_failed_kick_reports_idle_with_a_valid_ready_ball_state() -> None:
    runtime, clock = FakeRuntime(), Clock()
    runtime.finish_kick = lambda: KickMetrics(False, 0.0, 0.0)
    controller = ActionController(runtime, clock)

    controller.submit(KickCommand(Foot.LEFT))
    clock.now += controller.KICK_SETTLE_S
    controller.update()
    runtime.kicking = False
    controller.update()

    assert controller.telemetry_snapshot()["motion_state"] == "idle"
    assert controller.telemetry_snapshot()["ball_state"] == "ready"


def test_snapshots_only_expose_device_agent_ball_states() -> None:
    runtime, clock = FakeRuntime(), Clock()
    controller = ActionController(runtime, clock)

    snapshots = [controller.snapshot()]
    controller.submit(KickCommand(Foot.RIGHT))
    snapshots.append(controller.snapshot())
    clock.now += controller.KICK_SETTLE_S
    controller.update()
    snapshots.append(controller.snapshot())
    runtime.kicking = False
    controller.update()
    snapshots.append(controller.snapshot())

    assert {state["ball_state"] for state in snapshots} <= {"ready", "moving"}


def test_telemetry_snapshot_is_complete_and_tracks_actions() -> None:
    controller = ActionController(FakeRuntime())
    controller.submit(MoveCommand(Direction.LEFT))

    assert controller.telemetry_snapshot() == controller.snapshot()
    assert controller.telemetry_snapshot()["motion_state"] == "moving"
    assert controller.telemetry_snapshot()["vx"] == 0.2
    assert controller.telemetry_snapshot()["vy"] == 0.0
    assert controller.telemetry_snapshot()["yaw"] == 0.8
    assert controller.telemetry_snapshot()["active_action"] == "move"

    controller.submit(StopCommand())
    assert controller.telemetry_snapshot()["active_action"] == "none"

    controller.submit(KickCommand(Foot.RIGHT))
    assert controller.telemetry_snapshot()["active_action"] == "kick"
