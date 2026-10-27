# Link-impairment experiments with timing ground truth

`ros3_limassol.impairment` runs the standard arrival monitor against a
synthetic, seeded link model and scores it against **declared** outages. It
needs only the Python standard library and runs on virtual time, so a scenario
always produces the same report and recordings.

```sh
# From robotics/ros3_limassol
python -m ros3_limassol.impairment docs/impairment-example.json --record-dir runs/example
python -m ros3_limassol.evidence runs/example/usv02.jsonl --robot-id usv02
```

`--record-dir` writes one ordinary version-1 recording per robot (and refuses
to overwrite), so `replay`, `evidence` and `analysis` work on them unchanged.
The monitor counts in the report are exactly those replay produces. Pass the
matching `--robot-id` (the file name) and `--stale-after` to those tools; with
the default `usv01`, another robot's recording is rejected as `unexpected_robot`.

## Scenario

```json
{"seed": 7, "duration_s": 60, "tick_s": 0.1, "stale_after_s": 1.0,
 "robots": [{"robot_id": "usv01", "rate_hz": 10, "delay_s": 0.1, "jitter_s": 0.3,
             "loss": 0.05, "burst_loss": {"enter": 0.02, "exit": 0.2},
             "duplicate": 0.02, "outages": [[20, 24]], "restarts": [40]}]}
```

Unknown keys, overlapping outages, duplicate robot IDs and out-of-range values
are rejected. Per robot (all optional except `robot_id`):

| Key | Meaning |
| --- | --- |
| `rate_hz` | Publisher rate (default 10, at most 100). |
| `delay_s` | Fixed one-way delay added to every delivered sample. |
| `jitter_s` | Extra delay drawn uniformly from [0, `jitter_s`]. Jitter larger than the sample period reorders samples. |
| `loss` | Independent per-sample loss probability. |
| `burst_loss` | Gilbert–Elliott bursts: `enter` is the per-sample chance of entering the loss state, `exit` of leaving it. Mean burst length is about 1/`exit` samples. |
| `duplicate` | Chance a delivered sample arrives twice, each copy with its own jitter. |
| `outages` | Sorted `[start_s, end_s)` windows in which every sample is dropped. **These are the ground truth.** |
| `restarts` | Times at which the publisher restarts with a new `session_id` and sequence 0. |

Each robot has its own random stream seeded from `seed` and its `robot_id`, so
adding a robot never changes another robot's results. Every sample draws the
same random values in the same order whatever happens to it (common random
numbers), so adding an outage does not reshuffle delay or loss elsewhere.

## Report

Per robot, `link` counts generated, dropped (outage, independent loss, burst),
duplicated and delivered samples; `monitor` gives accepted/rejected counts,
rejection reasons and the final state.

`ground_truth.outages` pairs each declared outage with a STALE episode:

- **Detected:** a STALE episode starting between the outage start and
  `end + stale_after + delay + jitter + tick`, the latest moment the outage
  could first be observed. `detection_latency_s` = STALE time − outage start;
  `recovery_latency_s` = next HEALTHY time − outage end.
- **Already stale:** the link was already STALE when the outage began (a loss
  burst, or a preceding outage). Detected, but no latency is claimed.
- **Missed:** no such episode. This is expected for outages shorter than the
  stale threshold.

`unexplained_stale_episodes` are STALE episodes no outage accounts for; on a
synthetic link they come from random loss, bursts, or jitter gaps. They are
the false-alarm measure. Latencies are observed at receiver ticks or arrivals,
so they include up to one `tick_s` of quantisation.

## Results: choosing `stale_after_s`

A seeded sweep with 20 seeds per row, 300 s per run, 10 Hz publishing,
`tick_s` 0.05, and declared outages of 3 s (×2) and 0.8 s per run:

| Link | `stale_after_s` | 3 s outages detected | Mean detection latency (s) | 0.8 s outages detected | Unexplained STALE / hour | Rejected as out-of-order |
| --- | --- | --- | --- | --- | --- | --- |
| clean | 0.5 | 40/40 | 0.40 | 20/20 | 0 | 0% |
| clean | 1.0 | 40/40 | 0.90 | 0/20 | 0 | 0% |
| clean | 2.0 | 40/40 | 1.90 | 0/20 | 0 | 0% |
| delay 0.1 s + jitter 0.3 s | 0.5 | 40/40 | 0.69 | 20/20 | 0 | 25% |
| delay 0.1 s + jitter 0.3 s | 1.0 | 40/40 | 1.19 | 3/20 | 0 | 25% |
| independent loss 30% | 0.5 | 40/40 | 0.36 | 20/20 | 62 | 0% |
| independent loss 30% | 1.0 | 40/40 | 0.86 | 3/20 | 0 | 0% |
| bursty, mean burst 0.5 s | 0.5 | 38/40 (+2 already STALE) | 0.39 | 20/20 | 292 | 0% |
| bursty, mean burst 0.5 s | 1.0 | 39/40 (+1) | 0.88 | 3/20 | 105 | 0% |
| bursty, mean burst 0.5 s | 2.0 | 40/40 | 1.83 | 0/20 | 7 | 0% |
| bursty, mean burst 1 s | 0.5 | 34/40 (+6) | 0.39 | 20/20 | 410 | 0% |
| bursty, mean burst 1 s | 1.0 | 37/40 (+3) | 0.83 | 6/20 | 240 | 0% |
| bursty, mean burst 1 s | 2.0 | 38/40 (+2) | 1.78 | 0/20 | 71 | 0% |

Observations from this synthetic sweep:

1. On a clean link, detection latency is `stale_after_s` minus one sample
   period, and an outage is detectable only if the arrival gap it creates
   (outage length + one period) reaches the threshold.
2. **Fixed delay and jitter add directly to detection latency** (0.9 s → 1.19 s
   at a 1 s threshold), because the last pre-outage sample arrives late.
3. **Independent loss is harmless at a 1 s threshold but bursty loss is not.**
   Its false alarms are driven by burst length relative to the threshold: with
   1 s mean bursts, even a 2 s threshold raises about 71 unexplained STALE
   episodes per hour. A threshold should be chosen against the link's burst
   behaviour, not its average loss rate.
4. **Jitter beyond the sample period makes the monitor reject fresh samples.**
   With 0.3 s jitter at 10 Hz about a quarter of arrivals are rejected as
   `duplicate_or_out_of_order`, because the monitor requires strictly
   increasing sequence numbers. Liveness is unaffected, since accepted samples
   still refresh it, but the rejection count then overstates link damage.
   Whether to accept late in-session samples for liveness is an open design
   question; this tool only measures it.

## Live comparison on ArduPilot SITL

To check whether the model predicts a real stack, the same scenario can be
applied to live MAVLink traffic from ArduPilot SITL (issue #33):

```text
ArduPilot SITL ── MAVProxy ──> udp_impairment_relay ──> mavlink_bridge
                  (4 Hz)       :14550, scenario + seed     :14551, --tick 0.1
```

```sh
# From robotics/ros3_limassol, as in SITL.md; one terminal each
python -m ros3_limassol.mavlink_bridge --listen 127.0.0.1:14551 --stale-after 1.0 \
    --tick 0.1 --record live.jsonl --duration 350
python tools/udp_impairment_relay.py --listen 127.0.0.1:14550 --forward 127.0.0.1:14551 \
    --scenario docs/impairment-live-burst.json --warmup 30 --log relay.jsonl
Tools/autotest/sim_vehicle.py -v Rover --no-rebuild --mavproxy-args="--streamrate 4"
python tools/compare_impairment.py docs/impairment-live-burst.json relay.jsonl live.jsonl
```

**How live traffic is aligned with the model:**
- The relay forwards unchanged for `--warmup` seconds, which skips ArduPilot's
  1 Hz boot phase. The next `GLOBAL_POSITION_INT` defines t = 0.
- The k-th position datagram after that is sample k. It receives `link_fates`'
  k-th fate (burst state, independent loss, duplication, delays): the same
  random stream and draw order the virtual model gives its sample k.
- Every other datagram is dropped inside outages and while the latest sample
  left the burst model in its loss state; otherwise it is forwarded after the
  fixed delay.
- Outages are windows on the relay clock and drop everything.

`compare_impairment.py` aligns the bridge recording to the relay's t = 0,
replays it, and scores it with `match_outages`, the rule the virtual report
uses. Next to it, it runs the virtual model on the same scenario. Its **fate
agreement** line counts samples whose outcome (outage, burst, loss, forwarded)
matches the virtual model's. They can differ only where live timing moves a
sample across an outage boundary.

**Two structural differences to keep in mind:**
- **The bridge numbers samples in arrival order**, so on this path reordering
  and duplicates are never rejected; every arrival refreshes liveness. That
  matches the virtual model's `late_samples: "liveness"` policy when
  duplication is off, and does not match `reject`.
- **Live samples are not phase-locked to the scenario.** Virtual samples fall
  exactly on outage boundaries (for example t = 63.0 for an outage ending at
  63 s). Live ones arrive anywhere within the 0.25 s period, so live recovery
  includes the wait for the next position, about half a period on average.

The four profiles used are `docs/impairment-live-{clean,jitter,loss,burst}.json`.
Each runs at 4 Hz with `stale_after_s` 1.0 and outages of 3 s, 0.8 s and 3 s in
300 s. The seed is set per run.

## What this does not establish

The link model is synthetic. It is not a DDS, UDP, radio or MAVLink
measurement, does not model bandwidth, queueing or clock drift, and says
nothing about a real vehicle. Use it to choose and justify thresholds and to
define expected behaviour before comparing physical runs.
