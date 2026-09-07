from microduck_demo.send_velocity import PRESETS


def test_presets_only_expose_verified_policy_behaviors() -> None:
    assert PRESETS == {
        "forward": (0.25, 0.0, 0.0),
        "forward-left": (0.25, 0.0, 0.8),
        "forward-right": (0.25, 0.0, -0.8),
        "stop": (0.0, 0.0, 0.0),
    }
