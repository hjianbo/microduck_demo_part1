import math

import pytest

from microduck_demo.mqtt_control import MqttVelocityBridge


def test_validate_clamps_velocity() -> None:
    assert MqttVelocityBridge._validate({"vx": 9, "vy": 0, "yaw": 9}) == (
        0.25,
        0.0,
        0.8,
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"vx": True},
        {"vx": math.inf},
        {"speed": 1},
        {"vx": -0.2},
        {"vy": 0.1},
        {"vx": 0.0, "yaw": 0.8},
    ],
)
def test_validate_rejects_unsafe_payload(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        MqttVelocityBridge._validate(payload)
