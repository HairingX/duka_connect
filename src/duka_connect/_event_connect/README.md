# event_connect

Devices described by their points, independent of protocol. A protocol package - the one that
knows where a value lives and how it is encoded - builds its points and its client on these.

Nothing here performs I/O, sleeps, or knows a protocol. It imports nothing but the standard
library, so it can be a package of its own.

## What is here

| Module | What it holds |
|---|---|
| `_key` | `Key[T]`: a point's key, its text at runtime, carrying the type of its value |
| `_value` | `DataValue[T]` and `Quality`: a value, how far it can be trusted, when and what the device said |
| `_point` | `Point[T]`, by its behaviour, and its parts: `PollRate`, `Limits`, `Refresh`, `Change`, `Labels`, `Pulse`, `WriteKind`, `Transform` |
| `_scheduler` | `Scheduler`: which keys are due for a read, and when |
| `_events` | `Subscriptions`: who is told what, and when a change is a change |
| `_status` | `Status`: what a client knows of its device apart from its points |
| `_unit` | `Unit`: units of measurement, with their UCUM codes |
| `_certainty` | `Certainty`: how certain it is that a point is what its model says |
| `_errors` | The errors a client raises |
| `_clock` | `Clock`: the monotonic and the wall clock, behind one replaceable object |
| `_writes` | `Write[T]`: one write of a sequence |
| `testing` | `FakeClock`, and `FakePoint`, a point without a protocol |

## A point

`Point[T]` holds how a value behaves: how often it is read (`poll_rate`), what may be written
(`limits`), its `unit`, whether it is a setting or a command (`write_kind`), and what its write
or its change sets off (`on_write`, `on_change`). It refuses a contradiction when it is built,
naming every problem at once.

A protocol subclasses it with where the value lives and how it is encoded, says through
`readable` and `writable` which sides it has, and adds its own problems to `problems()`.

## Reading again

The device sends nothing by itself, and its points are read at different rates, so a change of
one can come long before another that follows from it is read. `Refresh(targets, after,
until_stable, when=...)` names those: read `targets` `after` seconds after a write (`on_write`) or
a change (`on_change`), and with `until_stable`, again every `after` seconds while they still
change, for at most that long - two reads in a row that agree end it. `when` limits a change to
one that rises or falls.

After a write, `after` left as None waits as long as the written point takes to read back, its
`read_back_after`; after a change, not at all.

## Polling

The scheduler decides; the client reads. `due()` lists the keys to read now, in order: extra
reads asked for by a refresh, then keys never read, then the most overdue. The client reads them,
then `record()`s each outcome, which also moves a read-until-settled along. `next_due()` says when
there is something to do next. Only polled keys - those a consumer subscribed to, or asked to be
polled - are read on their interval or by a refresh; a forced refresh reads any.
