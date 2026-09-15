from __future__ import annotations

from dataclasses import dataclass, field
import json
import queue
import socketserver
import threading
from typing import Any


@dataclass
class PendingCommand:
    payload: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(64 * 1024)
            if not raw:
                return
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            pending = PendingCommand(payload)
            self.server.mailbox.put(pending)  # type: ignore[attr-defined]
            if not pending.done.wait(3.0):
                result = {"code": 504, "msg": "simulator command timeout", "data": {}}
            else:
                result = pending.result
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            result = {"code": 400, "msg": str(exc), "data": {}}
        self.wfile.write((json.dumps(result, separators=(",", ":")) + "\n").encode())


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], mailbox: queue.Queue[PendingCommand]):
        self.mailbox = mailbox
        super().__init__(address, _Handler)


class LocalCommandServer:
    """Loopback-only JSONL adapter used before the Device Agent MQTT phase."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("the foundation demo command server must be loopback-only")
        self.mailbox: queue.Queue[PendingCommand] = queue.Queue(maxsize=32)
        self._server = _Server((host, port), self.mailbox)
        self._thread = threading.Thread(target=self._server.serve_forever, name="microduck-local-control", daemon=True)

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> None:
        self._thread.start()

    def poll(self) -> PendingCommand | None:
        try:
            return self.mailbox.get_nowait()
        except queue.Empty:
            return None

    @staticmethod
    def resolve(pending: PendingCommand, result: dict[str, Any]) -> None:
        pending.result = result
        pending.done.set()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
