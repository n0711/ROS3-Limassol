# ArduPilot SITL validation runbook (issue #28)

This is how to run the first validation of the receive-only MAVLink bridge
against ArduPilot SITL with independently known outages. It was first run on
27 October 2026 with ArduPilot `Rover-4.6.3`; the results are in
[VALIDATION.md](VALIDATION.md). Record any new run there too, and only after it
has actually been run.

```text
ArduPilot SITL ── MAVProxy ──(--out)──> udp_outage_relay ──> mavlink_bridge
   (vehicle)    (requests streams)     :14550, drops windows   :14551, receive-only
```

MAVProxy is the ground station that requests data streams; `--out` gives the
relay a copy. The relay forwards in one direction only, and the bridge only
receives, so nothing in the measured path sends to the vehicle.

## 1. Build SITL from a pinned tag

Use a stable Rover tag (`Rover-4.5.x` or newer). Record the exact tag and
commit, the OS and the Python version.

```sh
git clone --recurse-submodules --branch <Rover-tag> https://github.com/ArduPilot/ardupilot.git
cd ardupilot && git rev-parse HEAD
Tools/environment_install/install-prereqs-ubuntu.sh -y   # then open a new shell
./waf configure --board sitl && ./waf rover
```

## 2. Start the receivers, then SITL

Use three terminals. Commands 2a and 2b run from `robotics/ros3_limassol` in
this repository.

```sh
# 2a. Bridge: receive-only, records, stops after 180 s
python -m ros3_limassol.mavlink_bridge --listen 127.0.0.1:14551 --system-id 1 \
    --record sitl-stationary.jsonl --duration 180 > bridge-stationary.out

# 2b. Relay: outages at 30–35 s and 70–72 s after the first datagram
python tools/udp_outage_relay.py --listen 127.0.0.1:14550 --forward 127.0.0.1:14551 \
    --outage 30:35 --outage 70:72 --duration 120 --log relay-stationary.jsonl

# 2c. SITL with MAVProxy; sim_vehicle.py already sends a copy to 127.0.0.1:14550
Tools/autotest/sim_vehicle.py -v Rover --no-rebuild
```

Do not add `--out udp:127.0.0.1:14550`. `sim_vehicle.py` already passes
`--out 127.0.0.1:14550` to MAVProxy, and a second output to the same address
sends every message twice. The first run did add it. The relay forwarded only
the first source and counted the copy as `other_sources`, so the results were
unaffected. Without a terminal, also pass `--mavproxy-args="--non-interactive"`.

The relay's windows count from SITL's first datagram, while the bridge's
`--duration` counts from bridge start. The extra 60 s leaves room for SITL to
boot; if it takes longer, increase it so the bridge outlives the relay.

If the bridge summary shows `battery_unknown` or no accepted samples,
`GLOBAL_POSITION_INT` or `SYS_STATUS` is not streaming. In MAVProxy run
`set streamrate 10`, or set the `SR*_` parameters, and record what you set.

Expect `GLOBAL_POSITION_INT` at **1 Hz** for about the first 11 s of position
data (Rover's default `SRx_POSITION`), until MAVProxy's stream request takes
effect. Also expect the first few positions to be (0, 0), sent before the EKF
origin is set. A 1 Hz stream sits on the default `--stale-after 1.0`; see
[MAVLINK.md](MAVLINK.md#choosing---stale-after).

Run it **twice**: once stationary, and once while the vehicle moves so heading
and speed change. For example, in the MAVProxy console run `mode MANUAL`,
`arm throttle` (SITL may need `param set ARMING_CHECK 0`), `rc 3 1750` and
`rc 1 1650` to drive in a circle. A mission in `AUTO` or `GUIDED` moves also
works. Use new file names for the second run; the tools refuse to overwrite.
The first run was headless, so it sent the same RC overrides from a separate
pymavlink script on a second MAVProxy output (`--out udp:127.0.0.1:14560`). That
script is not part of this repository: it commands the simulated vehicle, and
nothing in the measured path does.

## 3. Collect the evidence

```sh
python -m ros3_limassol.replay sitl-stationary.jsonl --json > replay-stationary.jsonl
python -m ros3_limassol.evidence sitl-stationary.jsonl --robot-id usv01 > evidence-stationary.json
python tools/compare_outages.py relay-stationary.jsonl sitl-stationary.jsonl \
    --bridge-output bridge-stationary.out
```

`compare_outages.py` aligns the recording to wall-clock time from the receive
timestamps in its samples, replays it, and prints one row per relay window:

- **Arrival gap:** from the last datagram forwarded before the drop to the
  first one after it.
- **STALE after drop:** when the bridge went STALE, measured from the
  scheduled drop.
- **STALE − expected:** the difference from `last forwarded + stale_after`.
  On loopback this is normally between 0 and one bridge tick (0.5 s by
  default). It can be negative by up to one position interval, because the
  last forwarded datagram may be another message type sent after the last
  position.
- **HEALTHY after resume:** includes the wait for the next
  `GLOBAL_POSITION_INT`.

It also reports STALE changes that no window explains, and whether replay
reproduces the bridge's live transitions. A STALE after the relay has stopped
is expected and listed separately.

## 4. Acceptance (from issue #28)

- Two STALE→HEALTHY recoveries per run, each matched to a relay window.
- `Replay matches live: True`.
- `crc_errors` and `bad_length` are 0 in the bridge summary. If not, open a
  separate issue with a captured frame hex dump.
- Explain any nonzero `heading_unknown`, `battery_unknown`, `battery_stale` or
  `out_of_schema` count in one line.
- Coordinates in the recording match the SITL home location. This is a sanity
  check, not a positioning claim.
- Add a dated `VALIDATION.md` section: ArduPilot tag and commit, OS, Python,
  commands, the comparison tables, and an explicit **not established** list:
  no PX4, no MAVLink router, no companion computer, no radio or physical link,
  no signing.
- Do not commit `*.jsonl` recordings or logs; copy the key numbers instead.

## Tool self-check (not SITL)

The relay and comparison tools have unit tests in `tests/test_sitl_tools.py`.
They were also rehearsed end to end with a **pymavlink stand-in sender at
10 Hz**, not ArduPilot, sending through the relay to the bridge. Both scripted
outages were matched, and STALE came 0.06 s after the predicted
`last forwarded + 1.0 s` with a 0.1 s bridge tick. Replay matched the live
transitions to within 0.4 ms, and no CRC or length errors occurred. This shows
the tooling works; it is not autopilot validation.
