from __future__ import annotations

import argparse
import json
import socket
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control the foundation Microduck simulator over loopback")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    sub = parser.add_subparsers(dest="command", required=True)

    move = sub.add_parser("move")
    move.add_argument("direction", choices=("forward", "left", "right", "backward"))
    move.add_argument("--duration", type=float, default=2.0)
    sub.add_parser("stop")

    kick = sub.add_parser("kick")
    kick.add_argument("foot", choices=("left", "right"))

    ball = sub.add_parser("place-ball")
    ball.add_argument("position", choices=("center", "left_kick", "right_kick", "random"), default="center", nargs="?")
    sub.add_parser("status")
    return parser


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "move":
        return {"cmd": "move", "params": {"direction": args.direction, "duration_s": args.duration}}
    if args.command == "kick":
        return {"cmd": "kick", "params": {"foot": args.foot}}
    if args.command == "place-ball":
        return {"cmd": "place_ball", "params": {"position": args.position}}
    return {"cmd": args.command, "params": {}}


def send(payload: dict[str, Any], host: str, port: int, timeout: float = 4.0) -> dict[str, Any]:
    encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.sendall(encoded)
        response = connection.makefile("rb").readline(64 * 1024)
    if not response:
        raise RuntimeError("simulator closed the connection without a response")
    decoded = json.loads(response)
    if not isinstance(decoded, dict):
        raise RuntimeError("simulator returned a non-object response")
    return decoded


def main() -> None:
    args = _parser().parse_args()
    try:
        response = send(build_payload(args), args.host, args.port)
    except OSError as exc:
        raise SystemExit(f"cannot reach simulator at {args.host}:{args.port}: {exc}") from exc
    print(json.dumps(response, ensure_ascii=False, indent=2))
    if response.get("code") != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
