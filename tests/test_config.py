from pathlib import Path

from microduck_demo.config import load_config


def test_load_config_builds_session_scoped_topic(tmp_path: Path) -> None:
    path = tmp_path / "session.env"
    path.write_text(
        "MICRODUCK_SESSION_ID=abc123\n"
        "MICRODUCK_BROKER_HOST=example.test\n"
        "MICRODUCK_BROKER_PORT=1884\n"
        "MICRODUCK_TOPIC_PREFIX=demo/duck\n"
        "MICRODUCK_COMMAND_TIMEOUT=0.75\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.topic == "demo/duck/abc123/cmd/velocity"
    assert config.broker_host == "example.test"
    assert config.broker_port == 1884
    assert config.command_timeout == 0.75
