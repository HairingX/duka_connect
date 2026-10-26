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
| `ventilation_mode` | `B7` | 1 | 0 ventilation, 1 heat recovery, 2 supply | yes |
| `unit_type` | `B9` | 2 | the kind of unit | |
| `relay_sensor_enabled` | `14` | 1 | the relay sensor may start boost | yes |
| `analog_sensor_enabled` | `16` | 1 | the 0-10 V sensor may start boost | yes |
| `analog_sensor_level` | `2D` | 1 | the 0-10 V sensor's signal, 0 to 100 % | |
| `relay_sensor_active` | `32` | 1 | the relay sensor is on | |
| `supply_speed_1` … `exhaust_speed_3` | `3A`-`3F` | 1 each | supply and exhaust fan speed at speeds 1 to 3, 10 to 255 | yes |
| `fan2_rpm` | `4B` | 2 | the second fan's speed, 0 to 5000 rpm | |
| `filter_interval` | `63` | 2 | days between filter changes, 70 to 365 | yes |
| `clock_time` | `6F` | 3 | the unit's clock: seconds, minutes, hours | yes |
| `clock_date` | `70` | 4 | the unit's calendar: day, weekday 1 (Monday) to 7, month, year in the century | yes |
| `weekly_schedule` | `72` | 1 | the weekly schedule runs | yes |
| `cloud_enabled` | `85` | 1 | the unit may use Duka's cloud | yes |
| `ip_address` | `A3` | 4 | the unit's current IP address, its numbers in order | |
| `analog_sensor_threshold` | `B8` | 1 | the 0-10 V signal that starts boost, 5 to 100 % | yes |
| `restore_fan_speeds` | `012A` | 1 | command: the fan speeds of every speed back to the factory's, by the value 1 | command |
| `night_timer`, `party_timer` | `0302`, `0303` | 2 each | how long the night and party modes run: minutes, hours | yes |
| `humidity_over_threshold` | `0304` | 1 | the humidity is over its threshold | |
| `analog_sensor_over_threshold` | `0305` | 1 | the 0-10 V signal is over its threshold | |

A command is sent with function 02, which the unit does not answer; the points it changes are
read afterwards.

**Ventilation modes.** Ventilation moves air one way all the time; whether in or out is set by
the unit's DIP switch, and Duka recommends half of a home's units set each way, so that the
ventilation is balanced (DUKA One Pro 50 S Wi-Fi user manual, pages 12 and 14). Heat recovery
alternates, 70 seconds in and 70 seconds out, through the ceramic heat exchanger. Supply only
brings air in.

The guide gives the separate fan speeds `3A`-`3F`, the filter interval `63` and the restore
command `012A` for some models only; a unit without them answers `FD`, and they are `MISSING`.

Left out on purpose: the password `7D` and the Wi-Fi settings `94`-`A2`, as writing them can
lock out every client or take the unit off the network; restoring the factory settings `87`;
the schedule periods `77`, which are a feature of their own; and `32A`-`32B`, for another model
only.

## Not known yet

- **The unit type a Duka One reports.** The guide lists 3, 4, 5, 14 and 26-28 for Blauberg's
  own units, none of them a Duka One. `connect()` accepts any unit that reports a unit type;
  the live test prints it, and once known, other units can be refused as unsupported.
- **The battery voltage at which the app reports a flat battery.** Duka's app reports a CR1220
  to replace; `rtc_battery_voltage` is the likely source, but no document gives the threshold.
- **Which parameters a Duka One has.** The guide's table is for Blauberg's VENTO units; a unit
  without a parameter answers `FD`, and the point is `MISSING`.
