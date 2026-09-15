import threading

from device_agent_integration_demo.cli import send
from device_agent_integration_demo.local_control import LocalCommandServer


def test_loopback_server_round_trip() -> None:
    server = LocalCommandServer(port=0)
    server.start()
    host, port = server.address

    def simulate_main_loop() -> None:
        pending = None
        while pending is None:
            pending = server.poll()
        server.resolve(pending, {"code": 0, "msg": "ok", "data": pending.payload})

    worker = threading.Thread(target=simulate_main_loop)
    worker.start()
    payload = {"cmd": "stop", "params": {}}
    try:
        assert send(payload, host, port)["data"] == payload
    finally:
        worker.join(timeout=2)
        server.close()
