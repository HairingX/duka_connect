# Unit documentation

The manufacturers' documents this library is built from, each with its text layer for
searching. **The PDF is the authority**; the `.txt` files and `parameters.csv` are working
copies, and every row of `parameters.csv` carries the PDF page it came from.

All documents were downloaded on 2026-10-25.

| Folder | Document | Version | Source |
|---|---|---|---|
| `protocol/` | `vento-smart-home-connection-guide.pdf` - Connection to a "Smart Home" system, VENTO, connection guide (English) | PDF created 2026-03-19 | [blaubergventilatoren.net](https://blaubergventilatoren.net/download/vento-expert-a100-1-s10-w-v2-manual-14758.pdf) |
| `duka-one-pro-50-plus/` | `user-manual-da.pdf` - User manual for the DUKA One Pro 50+, in Danish; no English edition found | Version 1.0, November 2018 | [res.cloudinary.com](https://res.cloudinary.com/evoleska/image/upload/v1550217067/product/1699519.pdf), a retailer's copy |
| `duka-one-pro-50-s-wifi/` | `user-manual-da.pdf` - User manual for the DUKA One Pro 50 S Wi-Fi, in Danish; no English edition found | PDF created 2025-08-08 | [res.cloudinary.com](https://res.cloudinary.com/evoleska/image/upload/v1759831699/k5mr5ewrvolozqk7vbr6.pdf), a retailer's copy |

Not found:
- **Duka publishes no description of the unit's protocol.** The protocol is the one Blauberg
  describes for its VENTO units, which Duka's Wi-Fi units are controlled by through the DUKA
  Smart App. That a Duka One answers it as the guide says is to be confirmed on a unit.
- **No Duka One 50+ Wi-Fi manual.** The Pro 50+ manual of 2018 has no Wi-Fi; the Pro 50 S Wi-Fi
  manual is the nearest Wi-Fi edition, and is kept for its app setup and its controls.
- **No battery threshold.** No document says at which RTC battery voltage the app reports a flat
  battery.

## Extracts

| File | Content |
|---|---|
| `protocol/parameters.csv` | Every parameter of the guide's parameter table, pages 7-10, one row each, transcribed by hand. |
| `*.txt` | The text layer of each PDF (`pdftotext -layout`), for searching. Diagrams leave stray characters in it. |

`parameters.csv` columns: `number` (decimal), `hex`, `functions` (R read, W write without an
answer, RW write with an answer, INC and DEC increase and decrease with an answer), `name`,
`values`, `size` in bytes, `page`, and `note`, which says where the guide limits a parameter to
some models.

## What the documents say that is easy to miss

**Connection guide**
- The unit answers UDP on port 4000, also to a broadcast; a packet is at most 256 bytes
  (page 3).
- The device id is the 16 characters on the label of the control board or the casing. The
  word `DEFAULT_DEVICEID` takes its place for a search, which a unit answers with only 0x007C
  and 0x00B9 (page 4).
- The password is at most 8 characters, `1111` until changed in the app (page 4).
- A write with function 0x02 is not answered; 0x03 is (page 4).
- The checksum is the sum of every byte from the protocol type to the end of the data block,
  low byte first (page 4).
- The high byte of a parameter number is 0x00 at the start of every packet; 0xFF changes it for
  the parameters after it in that packet (page 4).
- Several parameters can be set to 2, "invert", which toggles them: on/off, the sensor
  activations, the weekly schedule, the cloud permission, DHCP.

**Duka manuals**
- The Pro 50 S Wi-Fi manual calls the device id the "Fan ID", printed on the board under the
  front cover, and gives the unit's own Wi-Fi network the default password `11111111`
  (page 16). That is the Wi-Fi password, not the protocol's.
- The remote control takes a CR2025 cell (both manuals). A CR1220 the app asks for is then
  most likely the unit's clock battery, whose voltage is parameter 0x0024; no document says so.
