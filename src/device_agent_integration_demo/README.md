# Device Agent Integration Demo — foundation simulator

This directory is the transport-neutral foundation for a Microduck + Device
Agent demo. Phase 1 deliberately validates the robot behaviors before adding
MQTT, ASR, or TTS. The local control socket accepts the same `cmd` / `params`
shape that Device Agent will publish later.

## Supported behavior

| Intent | Internal command | Status |
| --- | --- | --- |
| 往前走 | `move(direction=forward)` | Supported, bounded to 0.2–5 s |
| 往左 / 左转 | `move(direction=left)` | Supported as a forward-left curve |
| 往右走 / 右转 | `move(direction=right)` | Supported as a forward-right curve |
| 后退 | `move(direction=backward)` | Explicitly rejected: pinned policy is unreliable |
| 停止 | `stop` | Supported, highest locomotion priority |
| 左脚踢球 | `kick(foot=left)` | Supported; the ball is never repositioned |
| 右脚踢球 | `kick(foot=right)` | Supported; the ball is never repositioned |

`left` and `right` are not lateral motion or in-place turns. A new locomotion
policy must be trained and empirically accepted before `backward` can return
success.

## Initialize and run

Initialize the repository once:

```shell
./scripts/bootstrap.sh
```

Start the foundation simulator:

```shell
./scripts/run_device_agent_integration_demo.sh
```

The demo raises the ball's rolling friction from the upstream `0.0001` to
`0.003`, so a kick does not roll across most of the arena. It is a runtime
override and does not modify the pinned vendor model. Tune it when launching:

```shell
./scripts/run_device_agent_integration_demo.sh --ball-rolling-friction 0.005
```

The accepted range is 0 through 0.05; larger values stop the ball sooner.

The MuJoCo window stays in the first terminal. In a second terminal, submit
commands over the loopback-only control socket:

```shell
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli status
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli move forward --duration 2
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli move left --duration 2
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli move right --duration 2
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli stop
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli place-ball random
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli kick left
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.cli kick right
```

The socket binds to `127.0.0.1:8765` by default and is not a remote or security
boundary. MQTT replaces this adapter in the integration phase.

## Command contract

Commands intentionally use the Device Agent payload envelope:

```json
{
  "cmd": "move",
  "params": {"direction": "forward", "duration_s": 2.0},
  "requestId": "req-001",
  "ts": 1710000000000,
  "metadata": {"productId": "replace-in-device-agent"}
}
```

Allowed commands are:

- `move`: `direction` is `forward`, `left`, `right`, or `backward`; optional
  `duration_s` is finite and between 0.2 and 5.0.
- `stop`: no parameters.
- `kick`: required `foot` is `left` or `right`.
- `place_ball`: optional `position` is `center`, `left_kick`, `right_kick`, or
  `random`. This is a simulation maintenance command and need not be exposed to
  normal voice users.

Unknown fields, unknown commands, booleans masquerading as numbers, non-finite
durations, and out-of-range durations are rejected before reaching MuJoCo.

## Ball and kick semantics

The left and right kick policies were trained with a ball in a narrow window in
front of the selected foot. `kick` stops locomotion, waits 0.35 seconds, records
the ball's current position, and runs only the requested ONNX policy. It never
moves or resets the ball. Move the robot into a suitable pose before kicking;
otherwise it will kick air and report failure. A kick succeeds if peak ball
speed reaches 0.35 m/s or planar ball displacement reaches 0.08 m. This is
manual positioning, not autonomous visual ball seeking.

## DeviceSpec for product creation

The importable draft is [device-spec.json](./device-spec.json). It is the source
of truth for commands, properties, and events. Validate it in the exact locally
deployed Device Agent version before product creation, because schema support
can evolve. If that version supports enum constraints, constrain `direction`,
`foot`, and state strings to the values documented above.

Recommended natural-language instructions for the Device Agent are:

- “往左”“左转”“向左走” call `move` with `direction=left`.
- “往右”“右转”“向右走” call `move` with `direction=right`.
- Omitted movement duration means two seconds.
- “左脚踢球” and “右脚踢球” must preserve the requested foot.
- Never invent raw velocity values or commands outside the DeviceSpec.
- Explain that backward is unavailable when the device returns code 422.

## Future Device Agent MQTT mapping

Do not commit real Broker credentials. Copy the actual topics displayed by the
local Device Agent console. With default templates they are:

```text
commands:  device-agent/{productId}/device/{deviceId}/commands
responses: device-agent/{productId}/device/{deviceId}/responses
telemetry: v1/{productId}/{deviceId}/telemetry
events:    v1/{productId}/{deviceId}/event
```

Response example:

```json
{
  "code": 0,
  "msg": "accepted",
  "requestId": "req-001",
  "data": {"motion_state": "walking", "vx": 0.25, "yaw": 0.0},
  "ts": 1710000000000,
  "metadata": {"productId": "replace-in-device-agent", "source": "microduck-simulator"}
}
```

Online/state reports use only properties declared in the DeviceSpec:

```json
{
  "type": "status",
  "data": {
    "status": "online",
    "state": {
      "motion_state": "idle",
      "vx": 0.0,
      "yaw": 0.0,
      "active_action": "none",
      "kick_side": "none",
      "ball_state": "ready",
      "last_action_result": "none",
      "command_timeout_s": 1.0
    }
  },
  "ts": 1710000000000,
  "metadata": {"productId": "replace-in-device-agent", "source": "microduck-simulator"}
}
```

The MQTT phase must additionally preserve `requestId`, deduplicate one-shot
kicks, publish Last Will/offline status, enforce a movement deadman, report
state after every change, and convert drained controller events to Device Agent
event payloads.

## Phase-1 acceptance

Run:

```shell
vendor/microduck_rl/.venv/bin/pytest tests/device_agent_integration_demo
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.runner_builder
vendor/microduck_rl/.venv/bin/python -m json.tool \
  src/device_agent_integration_demo/device-spec.json >/dev/null
```

Automated tests cover validation, velocity mapping, bounded motion, stopping,
kick exclusivity/result reporting, explicit ball placement, the loopback
adapter, and DeviceSpec/implementation alignment. Visual MuJoCo acceptance is
then performed with the CLI commands above.
