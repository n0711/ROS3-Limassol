# Offline anomaly baseline and VERA-MOT research bridge

This is a strictly **offline, read-only research interface** for ROS3-Limassol.
It neither estimates GNSS position nor issues vehicle commands. It does not
convert receiver-arrival telemetry into measured packet loss, network delay,
jitter, sensor capture age or reliable communication claims.

## 1. Evidence input

Create JSON with the existing evidence exporter after obtaining a validated
ROS3 receiver-observation recording:

```sh
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 > evidence.json
python -m ros3_limassol.analysis features evidence.json > features.json
```

Feature version 1 uses only four bounded aggregate measures:

- rejected payload fraction = rejected / payload observations
- silence tick fraction = silence ticks / observation count
- observed STALE changes per tick = observed changes into STALE / observations
- maximum **observation tick** gap divided by configured timeout

These are *recorder-derived features*, not network packet loss or sensor
freshness metrics. The feature extractor omits raw telemetry and positions.
Input must be fully parsed evidence format v1 with consistent counters.

## 2. Fit and evaluate a baseline

Collect at least **five distinct receiver recordings** with comparable test
conditions, the same robot ID and the same monitor timeout. Each recording
must be exported separately. Example paths are illustrative:

```sh
python -m ros3_limassol.analysis fit \
  train01.json train02.json train03.json train04.json train05.json \
  > baseline-model.json

python -m ros3_limassol.analysis score \
  baseline-model.json held-out-evidence.json > anomaly-score.json
```

Training uses per-feature median and median absolute deviation (MAD). Its
robust deviation is:

```text
z = |x - median(training)| / max(1.4826 * MAD, feature_floor)
```

An exploratory outlier flag is raised for z > 3.5. The floor values are
predeclared regularizers, not field-calibrated operating thresholds. They prevent
division by zero when training data are identical. The model rejects duplicated
recording SHA-256 hashes, mismatched robot/timeout, unsupported versions and
training/held-out reuse.

The output means **statistical deviation from these training summaries only**.
It is not a neural model, VLM, GNSS-denied localization system or safety alarm.
If experimental conditions change, establish a new baseline and validation
protocol rather than inferring comparable accuracy.

## 3. Add VERA-MOT tracking and declared external VLM evidence

The [VERA-MOT project](https://github.com/n0711/vera-mot) handles multi-object
tracking, not language inference. Its optional offline exporters produce:

- `vision_evidence.py`: sequence-local MOT result counts and source hash.
- `vlm_contract.py`: aggregated labels and declared model/prompt/image
  provenance from *another* VLM workflow; does not run or verify a VLM.

Create separate ROS3, VERA, and optionally VLM JSON evidence reports, then:

```sh
python -m ros3_limassol.multimodal \
  evidence.json vision-evidence.json \
  --vlm vlm-evidence.json \
  --anomaly-model baseline-model.json > research-bundle.json
```

The `--vlm` and `--anomaly-model` flags may be omitted. The module checks
format/version and relevant source identifiers, reports separate aggregate
features and labels and **never claims aligned clocks, shared robot-to-video
identity, scene causality or navigation capability**. Do not mistake a common
`sequence` label for clock synchronization or an authenticated camera source.

## 4. Reproducibility and next research work

Record ROS distribution, software commit, receiver clock provenance, sample
and recording rate, independent outage schedule, camera time origin, video
rights and dataset split. The report fingerprint proves byte identity only,
not authenticity. Preserve private raw videos and telemetry in controlled
storage, not the LearnTwin browser planner.

For a publishable multimodal field claim, obtain hardware-based independent
ground truth, synchronize clocks with measured error bounds, run repeated
GNSS-denied and reconnection experiments, isolate model training and test
sets, and report error rates against predeclared baselines. Nothing in this
prototype establishes those claims.

## Check

From `robotics/ros3_limassol/`:

```sh
python -m unittest discover -s tests -v
python -m compileall -q ros3_limassol launch tests tools
```

Automated synthetic checks verify parser, CLI, privacy and evidence boundaries
but do **not** validate real robot performance.
