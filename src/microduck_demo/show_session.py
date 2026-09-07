from .config import load_config


def main() -> None:
    config = load_config()
    print(f"Session ID: {config.session_id}")
    print(f"Broker:     {config.broker_host}:{config.broker_port}")
    print(f"Topic:      {config.topic}")
    print(f"Timeout:    {config.command_timeout:g} s")


if __name__ == "__main__":
    main()
