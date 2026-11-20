# Duka Connect

An event-driven Python client for **Duka One** ventilation units on the local network, over the
unit's own UDP protocol.

You subscribe to the values you care about and are told when one changes - with its quality, so
"offline", "not on this unit" and a real value never look alike.

## Supported units

| Unit | Status |
|---|---|
| Duka One (S6W, 50+) | Points are from the manufacturer's connection guide; the clock battery's voltage has been read on a unit, the rest not yet |

**Every point is taken from the manufacturer's connection guide for the protocol, and most have
not been tested on a unit.** `point.certainty` says so: `REPORTED` until a point has been read
on a Duka One, `VERIFIED` after. Values may be wrong or missing; reports of what a unit shows are
welcome. What each point is: [docs/protocol.md](https://github.com/HairingX/duka_connect/blob/main/docs/protocol.md); the manufacturer's documents
themselves: [docs/models](https://github.com/HairingX/duka_connect/blob/main/docs/models/README.md).

## Installation

```bash
pip install duka-connect
```

Everything you use comes from `duka_connect`; a simulated unit for your own tests is in
`duka_connect.testing`. It depends only on `event_connect`, the protocol-free core it is built on.

## Usage

```python
import asyncio
from duka_connect import DEFAULT_PASSWORD, PointKey, create_client

def on_change(key, old, new):
    print(f"{key}: {new.value} ({new.quality.name})")

async def main():
    # The device id is in Duka's app; the password is 1111 unless it was changed there.
    client = create_client(host="192.0.2.10", device_id="<device-id>", password=DEFAULT_PASSWORD)
    await client.connect()              # reads every point once

    client.subscribe(PointKey.HUMIDITY, on_change)
    client.subscribe(PointKey.ALARM, on_change)
    client.subscribe(PointKey.RTC_BATTERY_VOLTAGE, on_change)

    await client.run()                  # reads whatever is due, whenever it is, until cancelled

asyncio.run(main())
```

`run()` sleeps until something is due, and wakes at once when a subscription, a write or a
`refresh()` makes something due sooner. It never ends by itself: while the client is not
connected - before `connect()`, or after `disconnect()` - it waits until it is, and a poll that
raises is logged, the first of a run of failures as an error with its traceback, and polling goes
on after a pause. It sleeps on the client's clock: a test that gives the client a `FakeClock`
moves it on with `clock.advance()`. To run your own loop instead, call `poll()`, which reads only
what is due - nothing when nothing is - and `seconds_until_next_poll()`, which says when to call it
again.

`await discover()` lists the units that answer a broadcast on the local network, and
`discover(target="192.0.2.10")` asks one address; each `DiscoveredDevice` has the `host` and
`port` it answered from, its `device_id` and its `unit_type`.

### The unit

`client.model` is `DUKA_ONE`, a `DukaModel`, with its `name`, `manufacturer`, `points` and how it
is read; `client.identity` is what the unit reports about itself, `{"unit_type": ...}`.
`client.points`, `has(key)`, `can_read(key)`, `can_write(key)` and `select(keys or labels)` tell
what the unit has: every point of the model. The client is a `DeviceClient`, used as the clients of the other
device libraries built on `event_connect` are.

`poll()`, `refresh()` and `write()` raise `NotConnectedError` until `connect()`, and again from
`disconnect()` until the next `connect()`; `points`, `model` and `seconds_until_next_poll()` raise
it until the first `connect()`.

### Values

Every value is a `DataValue` with `.value`, `.quality`, `.timestamp` (when the unit answered,
in UTC), and `.raw`: the bytes the unit answered.

| Quality | Meaning |
|---|---|
| `GOOD` | A value the unit answered. |
| `NO_DATA` | The unit answered a number no state names. |
| `STALE` | The last read failed; the value is the last good one. |
| `MISSING` | The unit says it does not have this value. |

`client.value(key)` is a point's value, None until it has one; `client.values` holds every
value read so far.

A subscribed point is read on its poll rate: `FAST` 10 s, `MEDIUM` 30 s, `SLOW` 60 s, `RARE`
15 min, or `STATIC`, once when connecting. The model says how often; nothing changes it.
`refresh()` reads now, or `after` seconds from now: a poll rate's points, keys, or everything. A
command among the keys is left out, as it has no value; a key a Duka One does not have raises
`KeyError`.

A point names what its change affects, in `on_change`, and a command what it changes, in
`on_write`: a `Refresh` of those points, after a wait, and read again until they settle where it
says so. When the alarm clears, the battery and filter are read 10 seconds later, and again every
10 seconds while they change, for up to 2 minutes; a new speed has the fans read 3 seconds later,
until they settle. What is read again is what is subscribed to. `docs/protocol.md` lists every one.

One request is sent at a time, and whatever is due when the unit is free goes out together. A
read asked for after a change does not move a point's own rhythm, so points read together stay
together. A request the unit does not answer is sent again, `attempts` times in all; a read still
unanswered waits for its next turn, and its value meanwhile is the last good one, `STALE`. Once
the unit answers again, whatever failed meanwhile is read at once. After two requests in a row go
unanswered, the unit is not asked for 10 seconds, so a pass over a silent unit fails at once
rather than waiting out every request; then one request probes it, and again every 10 seconds for
as long as it stays silent. Each request waits 2 seconds for an answer, and is sent 3 times.

The unit counts as not answering - `Status.CONNECTED` false - only once it has missed three reads
of its fastest poll rate, half a minute without an answer, so one lost packet does not make it
unavailable; when it answers again, every subscribed point is read. `disconnect()` makes it false
at once.

Every one of these numbers is a first estimate, set by the model and by `create_client`; none
can be changed from outside.

`client.status(Status.CONNECTED)` says whether the unit answers, and
`subscribe_status(Status.CONNECTED, callback)` tells every change. `client.diagnostics()` is for a
bug report, and never holds the address, device id or password:

| Key | Meaning |
|---|---|
| `requests`, `unanswered` | Requests sent, and those the unit left unanswered. |
| `refused_while_open` | Requests not sent, as the breaker was open. |
| `average_latency` | Seconds the unit took to answer, on average; None before its first answer. |
| `consecutive_unanswered` | Requests left unanswered since its last answer. |
| `open`, `open_for` | Whether the breaker is open, so the unit is not asked now, and for how many more seconds. |
| `openings` | How many times the breaker has opened since the unit last answered. |
| `gave_up` | Whether it is no longer asked at all; a Duka One is probed for as long as it is silent, so never. |
| `silent_for` | Seconds since its first request left unanswered since its last answer. |
| `writes` | The latest five writes sent to each key, the newest last; see below. |

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

`client.diagnostics()["writes"]` shows, for each key, the writes sent to it: the value asked for,
the bytes sent, when, and how it ended - `taken`, `refused`, `sent` for a command, which has no
answer, `no_answer` or `error` - with what the unit answered in `detail`: the value it has
instead, or that it does not have the parameter. Its `read_back` is the unit's next answer for
the key: for a setting, the value the unit answered the write with; otherwise the next read.

| Error | Meaning |
|---|---|
| `CannotConnectError` | The unit did not answer. A unit does not answer a wrong device id or password either. |
| `UnsupportedDeviceError` | The unit answered, but not as a Duka One does. |

## Measuring your unit

The waits after a change are first estimates, not yet measured on a Duka One.
`duka_connect.testing` measures how long yours takes to answer, reading only:

```python
from event_connect import SystemClock
from duka_connect.testing import measure_latency

print(await measure_latency(client, requests=20, clock=SystemClock()))
```

`tools/measure.py` also measures how long its fans take to reach a new speed, and the `after` and
`until_stable` that would follow them. It changes the unit's speed while it runs, and sets it back
afterwards:

```bash
DUKA_HOST=192.0.2.10 DUKA_DEVICE_ID=<device-id> python tools/measure.py
```

## Trying it on your unit

```bash
pip install -e . -r requirements-test.txt
DUKA_HOST=192.0.2.10 DUKA_DEVICE_ID=<device-id> python -m pytest -m live -s
```

It only reads, and prints what the unit answers for every point.

## License

MIT
