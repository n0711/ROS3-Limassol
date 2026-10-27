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
uses. It sets three results side by side:

- **Live:** the bridge recording.
- **Model, live timing:** the monitor fed with the live source's actual send
  times, plus the delays the relay applied, numbered in arrival order as the
  bridge numbers them. It differs from live only in the receive path:
  transport, bridge, battery gating and tick phase.
- **Model, nominal:** the virtual run, which assumes a perfectly periodic
  source. It differs from the live-timing model only in source timing: rate
  drift, phase and jitter.

The report also gives the live source's effective rate and its largest drift
from the model's sample times k / `rate_hz`. Its **fate agreement** line counts
samples whose outcome (outage, burst, loss, forwarded) matches the nominal
model's. They differ only where live timing moves a sample across an outage
boundary.

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

### Results: 20 live runs (27 October 2026)

**Setup:** five seeds per profile, 300 s each, on ArduPilot Rover 4.6.3 SITL
at 4 Hz, with bridge `--stale-after 1.0 --tick 0.1`, over loopback. Each cell
gives three values: **live · model with live timing · model nominal**. The
nominal model uses `late_samples: "liveness"`.

| Link profile | Runs | 3 s outages detected | Mean detection, 3 s (s) | 0.8 s outages detected | Mean recovery, 3 s (s) | Unexplained STALE per hour |
| --- | --- | --- | --- | --- | --- | --- |
| clean | 5 | 10 · 10 · 10 of 10 | 0.81 · 0.80 · 0.80 | 5 · 5 · 5 of 5 | 0.15 · 0.15 · 0.00 | 0 · 0 · 0 |
| delay 0.1 s + jitter 0.3 s | 5 | 10 · 10 · 10 of 10 | 1.09 · 1.09 · 1.07 | 5 · 5 · 5 of 5 | 0.38 · 0.38 · 0.24 | 0 · 0 · 0 |
| 30 % independent loss | 5 | 10 · 10 · 10 of 10 | 0.65 · 0.62 · 0.60 | 5 · 5 · 5 of 5 | 0.22 · 0.22 · 0.05 | 94 · 94 · 79 |
| bursts, mean 1 s | 5 | 10 · 10 · 10 of 10 | 0.79 · 0.80 · 0.77 | 3 · 3 · 5 of 5 | 0.11 · 0.11 · 0.25 | 142 · 142 · 139 |

**1. The receive path behaves as modelled.** Given the live source's actual
send times, the model reproduces:
- every recovery latency, to within 3.5 ms;
- every false alarm: 39 of 39 under loss and 59 of 59 under bursts;
- every detected or missed 0.8 s outage.

Detection latencies differ by at most 0.087 s, and on average by 0.005–0.021 s.
That is less than one 0.1 s bridge tick, whose phase is arbitrary live but
aligned with t = 0 in the model.

**2. Most of the gap is the source's timing, not the network.** The nominal
model assumes a perfectly periodic 4 Hz source. ArduPilot's stream actually ran
at 3.995–3.9996 Hz, with irregular intervals, and drifted up to 0.43 s from the
model's sample times. Because the live-timed model reproduces every case below,
each difference comes from source timing:
- **Recovery is wrong in both directions.** It is 0.00 s nominal against 0.15 s
  live on a clean link, because nominal samples land exactly on outage ends
  while live samples arrive anywhere within the 0.25 s period. It is 0.25 s
  against 0.11 s under bursts, because drift moves bursts relative to outage
  ends.
- **Loss false alarms are underestimated:** 79 against 94 per hour. Irregular
  source intervals lengthen some loss gaps past the 1 s timeout.
- **Burst detection of 0.8 s outages is overestimated:** 5/5 against 3/5. At
  4 Hz an 0.8 s outage leaves a gap only just over 1 s, so phase and drift
  decide whether it is reported.

**3. Reordering is invisible on the MAVLink path.** The bridge numbers samples
in arrival order, so it rejected nothing. Under the default `reject` policy,
the nominal model would have rejected 83 reordered samples in the jitter runs.

**Using the model for a real link:** drive it with the source's measured send
times, or at least model the source's rate offset and interval jitter. A
perfectly periodic source gives biased estimates of recovery and false alarms.

**Run quality:**
- Every run started HEALTHY at t = 0, and its recording covered the whole
  scenario.
- Fate agreement with the nominal model was 23,975 of 23,999 samples. The rest
  are boundary cases where a live sample fell on the other side of an outage
  edge.
- The relay's mean send error was 0.02–0.62 ms. Its largest single error was
  64 ms, in a jitter run, and no more than 11 ms in the other profiles.
- Bridge rejections, CRC errors and length errors were all 0. Each run withheld
  one sample at start-up (`battery_unknown`). Two burst runs each withheld one
  more (`battery_stale`). Each matches that run's only silent stretch longer
  than 5 s (5.01 s and 5.26 s), a single long burst that aged the battery report
  past `--battery-max-age`.

**Reproducibility and provenance.** To audit a run, preserve the exact
scenario JSON (including seed), relay JSONL log, bridge JSONL recording,
`compare_impairment.py --json` result, software commit, and SITL/MAVProxy
versions. The comparison tool checks the relay log's recorded scenario
settings and sample indices before scoring, so it rejects accidental
cross-seed or cross-profile comparisons. The 20-run aggregate table above
reports runs described in the validation record; **raw per-run logs and
recordings are not committed in this PR**, so the aggregate cannot be
independently re-scored from the repository alone.

## What this does not establish

The live comparison covers:
- one simulated vehicle on one host, over loopback, through MAVProxy;
- a 4 Hz stream with a single timeout (1.0 s);
- five seeds per profile.

False-alarm rates rest on 39 and 59 events and carry the corresponding
uncertainty. The impairments are applied by a relay, not a radio. Nothing here
covers signed MAVLink, PX4, or vehicle behaviour.


The link model is synthetic. It is not a DDS, UDP, radio or MAVLink
measurement, does not model bandwidth, queueing or clock drift, and says
nothing about a real vehicle. Use it to choose and justify thresholds and to
define expected behaviour before comparing physical runs.
