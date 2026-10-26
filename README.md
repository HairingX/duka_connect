# Duka Connect

An event-driven Python client for **Duka One** ventilation units on the local network, over the
unit's own UDP protocol.

You subscribe to the values you care about and are told when one changes - with its quality, so
"offline", "not on this unit" and a real value never look alike.

## Supported units

| Unit | Status |
|---|---|
| Duka One (S6W, 50+) | Untested: every point is from the manufacturer's connection guide, none read by this library yet |

**Every point is taken from the manufacturer's connection guide for the protocol, and has not
been tested on a unit.** `point.certainty` says so: `REPORTED` until a point has been read
on a Duka One, `VERIFIED` after. Values may be wrong or missing; reports of what a unit shows are
welcome. What each point is: [docs/protocol.md](https://github.com/HairingX/duka_connect/blob/main/docs/protocol.md); the manufacturer's documents
themselves: [docs/models](https://github.com/HairingX/duka_connect/blob/main/docs/models/README.md).

## Installation

```bash
pip install duka-connect
```

Everything you use comes from `duka_connect`; a simulated unit for your own tests is in
`duka_connect.testing`. The library has no dependencies.

## Usage

```python
import asyncio
from duka_connect import Client, PointKey

def on_change(key, old, new):
    print(f"{key}: {new.value} ({new.quality.name})")

async def main():
    # The device id is in Duka's app; the password is 1111 unless it was changed there.
    client = Client("<unit-ip>", "<device-id>", "1111")
    await client.connect()              # reads every point once

    client.subscribe(PointKey.HUMIDITY, on_change)
    client.subscribe(PointKey.ALARM, on_change)
    client.subscribe(PointKey.RTC_BATTERY_VOLTAGE, on_change)

    while True:                         # you own the clock; the library owns the plan
        await client.poll()             # reads only what is due - free when nothing is
        await asyncio.sleep(1)

asyncio.run(main())
```

`discover()` lists the units that answer a broadcast, with their address and device id.

### Values

Every value is a `DataValue` with `.value`, `.quality`, `.timestamp`, and `.raw`: the bytes the
unit answered.

| Quality | Meaning |
|---|---|
| `GOOD` | A value the unit answered. |
| `NO_DATA` | The unit answered a number no state names. |
| `STALE` | The last read failed; the value is the last good one. |
| `OFFLINE` | The unit has not answered since the client connected. |
| `MISSING` | The unit says it does not have this value. |

A subscribed point is read on its poll rate: `FAST` 10 s, `MEDIUM` 30 s, `SLOW` 60 s, `RARE`
15 min, or `STATIC`, once when connecting. `set_poll_interval(key, seconds)` changes one. A point
whose value changes has the points it affects read at once, such as the battery and filter when
the alarm clears.

### Writing

```python
from duka_connect import PointKey, Speed, VentilationMode

await client.write(PointKey.VENTILATION_MODE, VentilationMode.HEAT_RECOVERY)
await client.write_many([(PointKey.SPEED, Speed.MANUAL), (PointKey.MANUAL_SPEED, 120)])
await client.write(PointKey.RESET_FILTER_TIMER, None)   # a command
```

A setting is answered by the unit with its new value. A command is not answered, so what it
changed is read back after `command_delay` seconds, 1 unless given to `Client`.

A value outside a point's limits raises `InvalidValueError` before anything is sent; a value the
unit does not take raises `WriteError`.

| Error | Meaning |
|---|---|
| `CannotConnectError` | The unit did not answer. A unit does not answer a wrong device id or password either. |
| `UnsupportedDeviceError` | The unit answered, but not as a Duka One does. |

## Trying it on your unit

```bash
pip install -e . -r requirements-test.txt
DUKA_HOST=<unit-ip> DUKA_DEVICE_ID=<device-id> python -m pytest -m live -s
```

It only reads, and prints what the unit answers for every point.

## License

MIT
