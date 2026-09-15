# Device Agent Integration Demo — MQTT simulator

This directory contains a Microduck simulator that speaks the Device Agent
MQTT protocol. It subscribes to high-level `cmd` / `params` commands, executes
them in the MuJoCo main thread, and publishes correlated responses, state
telemetry, lifecycle status, and action events.

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

Start the MQTT-connected simulator:

```shell
./scripts/run_device_agent_integration_demo.sh
```

`bootstrap.sh` creates the ignored `.demo/device-agent.env` with a unique
anonymous test device on `broker.emqx.io`. To use a product created in Device
Agent, edit that file (or copy `device-agent.env.example`) and fill in the
values shown in its device access guide:

```dotenv
DEVICE_AGENT_BROKER=mqtts://zero.emqx.io:8883
DEVICE_AGENT_PRODUCT_ID=replace-with-product-id
DEVICE_AGENT_DEVICE_ID=replace-with-device-id
DEVICE_AGENT_USERNAME=replace-when-required
DEVICE_AGENT_PASSWORD=replace-when-required
DEVICE_AGENT_MQTT_QOS=1
DEVICE_AGENT_MQTT_KEEPALIVE=30
```

Real credentials stay under `.demo/`, which is gitignored. `mqtt://` and
`mqtts://` are both supported; TLS certificate verification is enabled for
`mqtts://`.

The demo raises the ball's rolling friction from the upstream `0.0001` to
`0.01`. After either kick or walking contact it also applies smooth exponential
velocity damping at `3.0/s`, including while the kick animation finishes. This
lets the ball roll visibly but prevents it crossing most of the arena. Both are
runtime overrides and do not modify the pinned vendor model. Tune them when
launching:

```shell
./scripts/run_device_agent_integration_demo.sh \
  --ball-rolling-friction 0.015 \
  --ball-velocity-damping 4
```

Rolling friction accepts 0 through 0.05 and velocity damping accepts 0 through
20. Larger values stop the ball sooner; set damping to zero for pure MuJoCo
contact physics.

At startup, and again whenever a ball moved by either a kick or walking contact
finishes slowing down, the demo spawns a new ball `0.43 m` straight ahead of
the robot. Colors rotate through orange, blue, yellow, magenta, cyan, and
green. Small physics jitter is ignored. The distance is calibrated for the
simple presentation loop:

```shell
.venv/bin/microduck-device-demo move forward --duration 5
.venv/bin/microduck-device-demo kick left
```

Depending on the robot's residual heading, use a short left/right correction
before kicking. Automatic respawn happens after the moved ball settles and
never as part of the `kick` command itself, so the kick still acts on the ball
at its current position.

The MuJoCo window stays in the first terminal. In a second terminal, submit
commands through the same MQTT Broker and Device Agent topics:

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

The simulator and CLI automatically load `.demo/device-agent.env`. To keep a
different configuration elsewhere, select it in the command terminal with:

```shell
export DEVICE_AGENT_MQTT_CONFIG="$PWD/.demo/device-agent.env"
```

Alternatively pass `--config .demo/device-agent.env` before the subcommand.
Each CLI invocation subscribes to the response topic before publishing, adds a
unique `requestId`, and waits only for its matching response.

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

## Device Agent MQTT mapping

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

The adapter currently implements the following guarantees:

- Responses preserve `requestId`, include `productId`, and use the documented
  Device Agent response envelope.
- QoS is configurable and defaults to 1. Retained commands are ignored.
- Completed request IDs are cached (last 128), so a redelivered one-shot kick
  returns its previous response without kicking twice.
- A retained online status is published after connect. MQTT Last Will publishes
  offline on an unclean disconnect; graceful shutdown publishes it explicitly.
- State telemetry is published whenever the controller snapshot changes, and
  controller events are published on the event topic.
- MuJoCo mutations remain on the simulator main thread; the MQTT network thread
  only validates the envelope and queues work.

## Acceptance

Run:

```shell
.venv/bin/pytest tests/device_agent_integration_demo
vendor/microduck_rl/.venv/bin/python -m device_agent_integration_demo.runner_builder
vendor/microduck_rl/.venv/bin/python -m json.tool \
  src/device_agent_integration_demo/device-spec.json >/dev/null
```

Automated tests cover validation, velocity mapping, bounded motion, stopping,
kick exclusivity/result reporting, explicit ball placement, MQTT configuration,
topic mapping, lifecycle/state/event envelopes, request correlation and
duplicate suppression, plus DeviceSpec/implementation alignment. Visual MuJoCo
acceptance is then performed with the MQTT CLI commands above.
