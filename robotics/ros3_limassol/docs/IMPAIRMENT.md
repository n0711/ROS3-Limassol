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

The optional top-level `late_samples` (`reject`, the default, or `liveness`)
selects the monitor's [late-sample policy](TELEMETRY.md#late-samples) for every
robot in the run, and is echoed in the report.

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
   The opt-in `late_samples: "liveness"` policy accepts such delayed, unseen
   samples. In this model it removes these rejections without raising maximum
   detection latency (comparison in [VALIDATION.md](VALIDATION.md)); the
   default remains `reject`.

## What this does not establish

The link model is synthetic. It is not a DDS, UDP, radio or MAVLink
measurement, does not model bandwidth, queueing or clock drift, and says
nothing about a real vehicle. Use it to choose and justify thresholds and to
define expected behaviour before comparing physical runs.
