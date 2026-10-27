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

Every value is a `DataValue` with `.value`, `.quality`, `.timestamp` (when the unit answered,
in UTC), and `.raw`: the bytes the unit answered.

| Quality | Meaning |
|---|---|
| `GOOD` | A value the unit answered. |
| `NO_DATA` | The unit answered a number no state names. |
| `STALE` | The last read failed; the value is the last good one. |
| `MISSING` | The unit says it does not have this value. |

A subscribed point is read on its poll rate: `FAST` 10 s, `MEDIUM` 30 s, `SLOW` 60 s, `RARE`
15 min, or `STATIC`, once when connecting. `set_poll_interval(key or poll rate, seconds)` changes
one, and `refresh()` reads now.

A point names what its change affects, in `on_change`, and a command what it changes, in
`on_write`: a `Refresh` of those points, after a wait, and read again until they settle where it
says so. When the alarm clears, the battery and filter are read 10 seconds later, and again every
10 seconds while they change, for up to 2 minutes; a new speed has the fans read 3 seconds later,
until they settle. What is read again is what is subscribed to. `docs/protocol.md` lists every one.

One request is sent at a time, and whatever is due when the unit is free goes out together. A
read asked for after a change does not move a point's own rhythm, so points read together stay
together. A read the unit does not answer is tried again a second later, then 2, 4 and 8 seconds
later, never later than its next turn; its value meanwhile is the last good one, `STALE`. The
unit counts as not answering - `Status.CONNECTED` false - only after half a minute without an
answer, so one lost packet does not make it unavailable. A different `Timing` can be given to
`Client`; `DUKA_ONE_TIMING` is the one a Duka One is read by.

`client.status(Status.CONNECTED)` says whether the unit answers, and
`subscribe_status(Status.CONNECTED, callback)` tells every change.

### Writing

```python
from duka_connect import PointKey, Speed, VentilationMode, Write

await client.write(PointKey.VENTILATION_MODE, VentilationMode.HEAT_RECOVERY)
await client.write_sequence([Write(PointKey.SPEED, Speed.MANUAL), Write(PointKey.MANUAL_SPEED, 120)])
await client.write(PointKey.RESET_FILTER_TIMER, True)   # a command, sent with True
```

A write returns whether the unit took it. A setting is answered by the unit with its new value,
which the client then holds. A command is not answered, so what it changed is read a second after
it is sent, at the next `poll()`.

A value outside a point's limits, or of another type, raises `InvalidValueError` before anything
is sent; a point that cannot be written raises `ValueError`.

| Error | Meaning |
|---|---|
| `CannotConnectError` | The unit did not answer. A unit does not answer a wrong device id or password either. |
| `UnsupportedDeviceError` | The unit answered, but not as a Duka One does. |

## Measuring your unit

The waits after a change are first estimates, not yet measured on a Duka One.
`duka_connect.testing` measures them on yours:

```python
from duka_connect.testing import measure_fan_settling, measure_latency, recommended_refresh

print(await measure_latency(client))               # how long the unit takes to answer
settlings = await measure_fan_settling(client)       # low to high and back; changes the speed
for settling in settlings:
    print(settling)
print(recommended_refresh(settlings, every=0.5))     # an `after` and an `until_stable` for the fans
```

`measure_fan_settling` changes the unit's speed while it runs, and sets it back afterwards.

## Trying it on your unit

```bash
pip install -e . -r requirements-test.txt
DUKA_HOST=<unit-ip> DUKA_DEVICE_ID=<device-id> python -m pytest -m live -s
```

It only reads, and prints what the unit answers for every point.

## License

MIT
