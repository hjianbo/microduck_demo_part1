import math

import pytest

from microduck_demo.mqtt_control import MqttVelocityBridge


def test_validate_clamps_velocity() -> None:
    assert MqttVelocityBridge._validate({"vx": 9, "vy": -9, "yaw": 9}) == (
        0.3,
        -0.2,
        1.5,
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"vx": True},
        {"vx": math.inf},
        {"speed": 1},
    ],
)
def test_validate_rejects_unsafe_payload(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        MqttVelocityBridge._validate(payload)
