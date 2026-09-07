# microduck_demo_part1

A reproducible MQTT control demo for the official Microduck MuJoCo walking policy.

The project pins the official [`microduck_rl`](https://github.com/pollen-robotics/microduck_rl) project and the official [Microduck Simulator](https://huggingface.co/spaces/pollen-robotics/microduck-simulator) as Git submodules. It adds a small Paho MQTT adapter; it does not modify motor control or policy inference.

## Prerequisites

- Git
- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- A desktop environment that can open the MuJoCo viewer

On macOS, the launcher automatically uses `mjpython` and locates the shared Python library from uv's managed Python installation.

## Initialize with one command

```shell
./scripts/bootstrap.sh
```

The command downloads the pinned submodules, installs Python dependencies, downloads and verifies the LFS-backed walking policy, builds the MQTT-enabled runner, and creates `.demo/session.env` with a random local session ID. The generated files are intentionally excluded from Git. Git LFS is not required.

## Run the demo

Start the simulator in the first terminal:

```shell
./scripts/run_simulator.sh
```

Send a velocity command from a second terminal:

```shell
./scripts/send.sh forward --duration 3
```

The pinned walking policy is reliable for forward motion and turning while moving forward. Use these verified presets:

```shell
./scripts/send.sh forward-left --duration 3
./scripts/send.sh forward-right --duration 3
./scripts/send.sh stop
```

Custom forward and turn values are also supported:

```shell
./scripts/send.sh forward --duration 3 --vx 0.2 --yaw 0.5
```

The current policy does not reliably walk backward or turn in place, and the official simulator explicitly disables strafing. The sender and receiver therefore reject those command combinations instead of presenting them as supported behavior.

The sender refreshes the command at 10 Hz and always publishes a final zero-velocity message. The simulator independently resets velocity after one second without a valid command.

To verify the independent receiver-side deadman, intentionally omit the final stop in this simulation-only test:

```shell
./scripts/send.sh forward --duration 1 --test-deadman
```

The simulator should log `MQTT: command timeout; velocity reset to zero` about one second after the last velocity message.

Show the generated session and Topic:

```shell
MICRODUCK_MQTT_CONFIG="$PWD/.demo/session.env" \
  vendor/microduck_rl/.venv/bin/microduck-session
```

## Safety properties

- Every checkout generates a different session-scoped Topic.
- Velocity messages use QoS 0 and `retain=false`.
- Retained velocity messages are ignored by the simulator.
- Payloads are type-checked, finite-checked, and clamped to the policy ranges.
- A local one-second deadman resets velocity after silence or disconnect.
- MQTT carries velocity intent only; it never writes joint or motor targets.

`broker.emqx.io:1883` is a public, unencrypted test broker. Do not send sensitive data. Use a private TLS-enabled broker with authentication and narrowly scoped Topic permissions for any non-demo environment.

## Updating upstream dependencies

The submodules are pinned so the demo and generated runner remain reproducible. Update them deliberately, then run the generator and tests before committing the new pins:

```shell
git submodule update --remote vendor/microduck_rl vendor/microduck_simulator
vendor/microduck_rl/.venv/bin/python scripts/build_runner.py
vendor/microduck_rl/.venv/bin/pytest
```
