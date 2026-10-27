# Offline observation evidence, report format 1

ROS3-Limassol can produce a reproducible, bounded-memory JSON report from an
**existing** version-1 receiver observation recording. The command is read-only,
uses Python standard-library modules and has no ROS or vehicle-command dependency.

## Generate a report

Run from `robotics/ros3_limassol/`:

```sh
python -m ros3_limassol.demo --record run.jsonl
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 --stale-after 1.0 > evidence.json
```

Use a new recording path for every demo or separate recording session: recording
creation refuses to overwrite an existing file. To compare thresholds, run
the evidence command twice with different `--stale-after` values, preserving
each output separately. Reports are calculated from the same input bytes.

No partial JSON is emitted when parsing fails. If using shell redirection,
the shell may still create an empty output file before the command fails.
Check the command's exit status before retaining or publishing a report.

## Interpreting the fields

| Field | Definition |
| --- | --- |
| `recording_sha256` | SHA-256 of the exact input file bytes, including whitespace and line endings |
| `recording_parsed_to_eof` | Full recording-envelope validation reached end-of-file |
| `observation_count` | Number of recording envelopes (including silent ticks) |
| `payload_observation_count` | Envelopes containing raw telemetry text, **not** a sent-packet estimate |
| `silence_tick_count` | Explicit null observations in this recorder, **not** proven packet losses |
| `first_observation_s`, `last_observation_s` | Receiver-relative times in the recording |
| `max_between_observation_gap_s` | Longest gap between consecutive recorded observations, or null for fewer than two |
| `accepted`, `rejected` | Results from the existing `LinkMonitor` against this file and selected robot ID |
| `rejection_reasons` | Counts of monitor rejection categories |
| `late_samples`, `late_accepted` | The monitor's late-sample policy (`reject` by default, or `liveness` via `--late-samples`) and how many late, unseen in-session samples it accepted; see [TELEMETRY.md](TELEMETRY.md#late-samples). Compare reports only with matching policies. |
| `first_accepted_arrival_s`, `last_accepted_arrival_s` | Recorded receiver-relative times of accepted payloads |
| `final_state`, `final_age_s` | Monitor state and time since its last accepted arrival at the final observation |
| `observed_state_change_count` | Total WAITING/HEALTHY/STALE changes observed at recorded times |
| `observed_stale_change_count` | Number of observed transitions into STALE |
| `observed_stale_to_healthy_recoveries` | Number of observed STALE-to-HEALTHY transitions |
| `recent_state_changes` | Last 256 observed changes with their observation times |
| `state_changes_truncated` | True when more than 256 state changes occurred |

The report has `report_version: 1`; this refers to **report format**, separately
from the observation recording's own `record_version: 1`.

The exporter parses recordings incrementally, retains only aggregate counters
and a bounded transition tail, and does not emit raw positions, battery values,
telemetry payloads, or sender timestamps. It uses the same receiver-arrival
monitor as replay, so recorded invalid payloads are counted as rejected rather
than treated as unreadable envelopes.

## Research validity and reproducibility

The report **does not** establish transmitted-message counts, packet delivery
ratio, one-way network delay, network jitter, upstream sensor capture age,
navigation accuracy, vehicle health or field reliability. The largest
**observation** gap can also reflect sparse recorder ticks, callback scheduling,
or pauses, not only network silence. The first/last observed transitions are
measured on the recording's tick grid: precise transition times between ticks
are not inferred.

For a scientific experiment, retain this report alongside:

- The source recording (with any sensitive robot/location information protected)
  and a separately controlled, timestamped experimental log.
- Software version/commit, ROS distribution, platform, clock assumptions,
  chosen timeout, recorder parameters and observation tick period.
- An independent source of ground truth for each outage/recovery interval.
- Documented test conditions, repeat count, exclusions and any recorder errors
  or dropped/unrecordable message counts available from separate logs.

SHA-256 fingerprints identify input-byte equality but are **not digital
signatures**, provenance, completeness or authenticity proofs. The JSON report
omits the original coordinates but is not automatically anonymous if joined
with other logs. Do not publish sensitive field recordings without reviewing
their contents and rights.

## Verification

From the package directory:

```sh
python -m unittest discover -s tests -v
python -m compileall -q ros3_limassol launch tests tools
```

The evidence tests reproduce the deterministic simulation, check corrupted
input and rejection semantics, verify exact SHA-256 fingerprints and enforce a
bounded tail of state changes. CI exercises the installed wheel from a directory
outside the source checkout. A passing test is software evidence, not a
physical-robot validation.
