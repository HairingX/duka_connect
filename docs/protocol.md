# The Duka One's protocol

The unit answers UDP on port 4000. This page sets out the packet format and every point the
library reads, as the manufacturer's connection guide describes them:
`docs/models/protocol/vento-smart-home-connection-guide.pdf`, with its parameter table in
`docs/models/protocol/parameters.csv`. No point has been read on a Duka One by this library yet,
so every point is `Certainty.REPORTED`.

## Packets

```text
FD FD                 header
02                    protocol type
n  <device id>        the id's length, then the id (16 characters)
n  <password>         the password's length, then the password ("1111" unless changed)
f                     function: 01 read, 02 write, 03 write and answer, 04 increase, 05 decrease, 06 answer
<parameters>
lo hi                 checksum: the sum of every byte after the header, low byte first
```

Each parameter is its number's low byte, followed in a write or an answer by its value, low byte
first. Markers before a parameter:

| Marker | Meaning |
|---|---|
| `FF p` | The parameters after it are on page `p`: their numbers are `p << 8` plus the byte. It holds until the next `FF`, within one packet; every packet starts on page 0. |
| `FE n` | The next parameter's value is `n` bytes. Without it, the value is one byte, or the size the parameter is known to have. |
| `FD x` | In an answer: the unit does not have parameter `x`. The point is `Quality.MISSING`. |
| `FC f` | In an answer: the function changes to `f`. Skipped. |

A unit does not answer a wrong password, nor a write with function 02.

## Points

| Key | Parameter | Bytes | Meaning | Write |
|---|---|---|---|---|
| `power` | `01` | 1 | 0 off, 1 on | yes |
| `speed` | `02` | 1 | 1, 2 or 3, or 255 for the manual speed | yes |
| `boost` | `06` | 1 | boost runs | |
| `timer_mode` | `07` | 1 | 0 off, 1 night, 2 party | yes |
| `timer_countdown` | `0B` | 3 | seconds, minutes, hours left of the timer | |
| `humidity_sensor_enabled` | `0F` | 1 | the humidity sensor may start boost | yes |
| `humidity_threshold` | `19` | 1 | %RH that starts boost, 40 to 80 | yes |
| `rtc_battery_voltage` | `24` | 2 | the clock's battery, 0 to 5000 mV | |
| `humidity` | `25` | 1 | %RH | |
| `manual_speed` | `44` | 1 | 0 to 255, used while `speed` is 255 | yes |
| `fan_rpm` | `4A` | 2 | the fan's speed, 0 to 5000 rpm | |
| `filter_timer` | `64` | 3 | minutes, hours, days until the filter is due | |
| `reset_filter_timer` | `65` | 1 | command: start the filter timer again | command |
| `boost_off_delay` | `66` | 1 | minutes boost runs on, 0 to 60 | yes |
| `operating_time` | `7E` | 4 | minutes, hours, and days in two bytes the unit has run | |
| `reset_alarms` | `80` | 1 | command: clear the alarms | command |
| `alarm` | `83` | 1 | 0 none, 1 alarm, 2 warning | |
| `firmware_version`, `firmware_date` | `86` | 6 | major, minor, day, month, year in two bytes | |
| `filter_replace` | `88` | 1 | 0 the filter is fine, 1 replace it | |
| `ventilation_mode` | `B7` | 1 | 0 extract, 1 heat recovery, 2 supply | yes |
| `unit_type` | `B9` | 2 | the kind of unit | |

A command is sent with function 02, which the unit does not answer; the points it changes are
read afterwards.

## Not known yet

- **The unit type a Duka One reports.** The guide lists 3, 4, 5, 14 and 26-28 for Blauberg's
  own units, none of them a Duka One. `connect()` accepts any unit that reports a unit type;
  the live test prints it, and once known, other units can be refused as unsupported.
- **The battery voltage at which the app reports a flat battery.** Duka's app reports a CR1220
  to replace; `rtc_battery_voltage` is the likely source, but no document gives the threshold.
- **Which parameters a Duka One has.** The guide's table is for Blauberg's VENTO units; a unit
  without a parameter answers `FD`, and the point is `MISSING`.
