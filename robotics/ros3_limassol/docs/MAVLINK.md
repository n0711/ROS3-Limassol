# Receive-only MAVLink adapter (experimental)

`ros3_limassol.mavlink_bridge` listens for MAVLink on a UDP socket, maps two
messages onto [telemetry schema v1](TELEMETRY.md) and feeds the existing arrival
monitor and, optionally, the [observation recorder](RECORDING.md). It needs only
the Python standard library; pymavlink is **not** required.

```sh
# From robotics/ros3_limassol
python -m ros3_limassol.mavlink_bridge --listen 127.0.0.1:14550 --record run.jsonl
python -m ros3_limassol.replay run.jsonl --stale-after 3
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 --stale-after 3 > evidence.json
```

The bridge's default `--stale-after` is 3.0 s; replay and evidence default to
1.0 s, so pass the bridge's value to them, as above. See
[Choosing `--stale-after`](#choosing---stale-after).

The bridge prints one JSON line per link-state change and a summary on exit
(Ctrl+C or `--duration`). The summary includes MAVLink framing counters and
mapping counters so withheld samples are visible.

## Receive-only boundary

The bridge binds a socket and only receives. The package contains no MAVLink
encoder and no send call, and a test checks this. Consequently it never sends
heartbeats, requests data streams, or sends parameters, missions or commands.

The sender must already push MAVLink to the bridge's address. ArduPilot's
`sim_vehicle.py` already gives MAVProxy `--out 127.0.0.1:14550`, the bridge's
default address; add another `--out` only for a different address, since a
second output to the same address delivers every message twice. For a MAVLink
router, add a UDP client endpoint pointing at the bridge. Some autopilot links
only stream data after a ground station requests it; with such a link, run a
GCS or router that requests streams and forwards a copy to the bridge.

## Choosing `--stale-after`

Only `GLOBAL_POSITION_INT` produces samples, so `--stale-after` must clearly
exceed the slowest interval at which the vehicle sends that message, plus
jitter. Detection then takes about `--stale-after` plus up to one `--tick`
(0.5 s by default).

**The default is 3.0 s.** ArduPilot Rover's default `SRx_POSITION` stream rate
is **1 Hz**. In the [SITL validation](VALIDATION.md), position arrived at 1 Hz
for the first 11 s of position data, until MAVProxy's 4 Hz request took effect.
Gaps of 0.990–1.009 s straddled the bridge's former 1.0 s default. No false
`STALE` occurred, but only because no tick landed in the few milliseconds when
the age exceeded 1.0 s. A default of three position intervals at 1 Hz avoids
that. The price is that an outage is reported about 3–3.5 s after the last
sample, and a gap shorter than 3 s is not reported at all.

For faster detection, have the ground station or router request a higher rate,
for example `SRx_POSITION` 4 or MAVProxy `--streamrate 4`. Then pass a smaller
`--stale-after` that is still several intervals long, such as 1.0 s at 4 Hz.

The recording does not store the threshold. Pass the same `--stale-after` to
`replay` and `evidence`; their default is 1.0 s. The bridge summary reports
`stale_after_s`.

## Message mapping

One telemetry sample is produced for each accepted `GLOBAL_POSITION_INT` from the
configured source.

| Schema v1 field | MAVLink source | Conversion |
| --- | --- | --- |
| `latitude_deg` | `GLOBAL_POSITION_INT.lat` (degE7) | ÷ 10^7 |
| `longitude_deg` | `GLOBAL_POSITION_INT.lon` (degE7) | ÷ 10^7 |
| `heading_deg` | `GLOBAL_POSITION_INT.hdg` (cdeg) | ÷ 100; 65535 means unknown |
| `speed_m_s` | `GLOBAL_POSITION_INT.vx`, `vy` (cm/s, NED) | horizontal magnitude ÷ 100 |
| `battery_pct` | latest `SYS_STATUS.battery_remaining` (%) | −1 means unknown |
| `robot_id` | `--robot-id` | configured, not from MAVLink |
| `session_id` | adapter | `mav<sysid>_<random>`, new per bridge process |
| `sequence` | adapter | 0, 1, 2… per accepted sample, in arrival order (so the monitor never sees a late sample; `late_samples` does not apply) |
| `timestamp_ns` | receiver wall clock | `time_boot_ms` is not Unix time |

A sample is **withheld** (not published, recorded or counted as rejected) and a
mapping counter incremented when:

- the frame is from another system ID (`--system-id`, default 1) or, if set,
  another component ID (`other_source`);
- heading is 65535 (`heading_unknown`);
- no `SYS_STATUS` has arrived, or it reported −1 (`battery_unknown`);
- the latest battery report is older than `--battery-max-age` seconds,
  default 5 (`battery_stale`);
- a converted value is outside schema v1, e.g. heading ≥ 360° or speed above
  100 m/s (`out_of_schema`). Invalid headings are rejected, not wrapped.

Withheld samples are absent from recordings, so a source that only sends
position without battery appears as silence. Check the summary counters.

After an outage longer than `--battery-max-age`, the first position can arrive
before a fresh `SYS_STATUS` and is then withheld as `battery_stale`, delaying
recovery by up to one position interval. In SITL this happened once after the
5 s outage: `HEALTHY` returned 0.32 s after traffic resumed, versus 0.08 s after
the 2 s outage.

## Framing

MAVLink 1 (`0xFE`) and MAVLink 2 (`0xFD`) frames are parsed incrementally from
any chunking. Only `SYS_STATUS` (1) and `GLOBAL_POSITION_INT` (33) are
checksum-verified with their `CRC_EXTRA` and decoded. Truncated MAVLink 2
payloads are zero-padded as the protocol specifies. Counted outcomes:

- `frames`: verified, decoded frames.
- `unsupported_messages`: other message IDs, skipped by declared length without
  verification.
- `crc_errors`: checksum mismatch; the parser drops one byte and resynchronises.
- `signed_skipped`: MAVLink 2 signed frames. Signatures are **not verified**, so
  these frames are skipped rather than trusted.
- `bad_length`: a verified frame whose length does not match the message.
- `bytes_discarded`: bytes outside any frame.

Parser tests include frames encoded independently by pymavlink 2.4 in both
protocol versions.

## What this does not establish

- `GLOBAL_POSITION_INT` may be sent without a GNSS fix (often as 0, 0). The
  adapter does not read `GPS_RAW_INT` and does not infer fix quality.
- Battery percentage is the autopilot's estimate, attached to the next position
  sample; the two are not captured at the same instant.
- `HEALTHY` remains receiver arrival recency, as elsewhere in ROS3-Limassol. It
  says nothing about vehicle safety or the autopilot's own link-loss failsafe.
- Source identity is not authenticated. Frames are filtered only by MAVLink
  system/component ID, not by sender address. If `--listen` binds beyond
  loopback (for example `0.0.0.0`), any host that can reach the port can send
  unsigned frames with the configured system ID and hold the monitor in
  `HEALTHY`. Keep the default `127.0.0.1` bind, or restrict the port with a
  firewall, when the network is not trusted.
- Unsupported messages cannot be checksum-verified, because their `CRC_EXTRA`
  is unknown, so they are skipped by their declared length. A stray `0xFE`/`0xFD`
  byte in line noise followed by a plausible header can therefore swallow a
  valid frame that follows it; that frame is lost, not misread.
- MAVLink 2 signing, serial ports, TCP, and multiple vehicles per bridge are not
  supported. Run one bridge per system ID.
- Validated in automated tests, a local UDP run with a pymavlink sender, and
  ArduPilot Rover 4.6.3 SITL over loopback with scripted outages (see
  [VALIDATION.md](VALIDATION.md) and the [SITL runbook](SITL.md)). No PX4 SITL,
  companion computer, radio or physical vehicle link has been verified.
