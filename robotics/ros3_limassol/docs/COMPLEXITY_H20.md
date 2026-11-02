# H20 — Reproducible Raspberry Pi Evidence Collection (software-only)

Date: 2026-11-02. This milestone adds **collection and integrity tooling**,
not Raspberry Pi 3B measurements or a decision to migrate the monitor.

## Goal and scope

Use the H14, H16, H17, H18 and H19 synthetic probes from one pinned checkout
and collect their exact JSON reports under one new evidence directory.
The CLI records a Git commit ID, Python/platform labels, CPU-count and optional
device-model label. SHA-256 hashes identify the report bytes and make accidental
tampering detectable after copying the directory.

A successful GitHub CI run demonstrates that the commands work on GitHub's
runners. **It does not mean the Raspberry Pi was tested.**

The production `ros3_limassol.monitor.LinkMonitor`, telemetry schema, ROS 2
nodes, safety boundaries, and optional H18 ring are unchanged. The collector
does not open serial, MAVLink, UDP or radio transports.

## Collect on Raspberry Pi 3B (Arduinos disconnected)

From the Raspberry Pi shell:

```sh
cd ~/projects/ROS3-Limassol
git switch main
git pull --ff-only origin main
git status --short
cd robotics/ros3_limassol

python3 -m unittest discover -s tests -v

# The destination must NOT exist; use a unique name for every run.
python3 tools/capture_h20.py \
  --output-dir ~/h20-pi3b-2026-11-02-run01

python3 tools/verify_h20.py ~/h20-pi3b-2026-11-02-run01
```

The normal preset executes:

- **H14**: input-size scaling for default/late ingestion and streaming replay;
- **H16**: independent, sequential multi-monitor scaling;
- **H17**: single-ingest latency including large late-window expiry;
- **H18**: current heap and experimental ring on identical synthetic frames;
- **H19**: finite exhaustive equivalence over its specified event alphabet.

Each executable enforces its own limits. Each is invoked with a fixed Python
argument vector, never a shell command. Python and Python-tracked memory are
measured separately where the individual benchmark says so. H19 has no
performance timings; it provides an equivalence test over a finite state-space.

For a small local command smoke test instead of the full preset:

```sh
python3 tools/capture_h20.py \
  --quick --output-dir ~/h20-quick-check-01
python3 tools/verify_h20.py ~/h20-quick-check-01
```

The manifest marks such a bundle `run_mode=quick_ci_smoke`. This is NOT a
Pi performance baseline even if executed on a Pi: the tiny workloads are
intended only for interface validation.

## Evidence and verification contract

A complete capture produces `manifest.json` and exactly five individual
`h14.json` through `h19.json` reports (H15 is a two-report comparison
utility and is not part of this single-run bundle).

The manifest contains:

- `git_commit` and `tracked_repository_clean` (untracked files excluded);
- `captured_at_utc`, OS/Python/machine labels, CPU-count and optional
  `device_model_label` from `/proc/device-tree/model`;
- the exact benchmark command arguments, raw file sizes and SHA-256 hashes;
- explicit negative claims for physical validation, hard-real-time,
  asymptotic proof, ring migration and any automatic Pi identity verification.

If a command fails, the tool leaves an **incomplete** directory without
`manifest.json` (and writes `FAILED.txt` for a nonzero subprocess exit).
The verification tool then refuses it. The collector refuses an already
existing destination to preserve older evidence.

`verify_h20.py` checks all expected files, commands, SHA-256 values,
payload sizes, report schema and negative claims. Hashes are not signatures
and cannot authenticate a physical machine or the author of a report.
A device-model string is informative only and must not be used as a
cryptographically verified identity.

## Mathematical interpretation and decision

Let `R` be receiver instances, `N` accepted samples, `B` input bytes,
`S` retained sessions, and `W` the late-sequence window.

```text
Reference heap monitor:
  expected aggregate processing O(N * (B + log(W+1)))
  single late-window-expiry call may require O(W log(W+1)) heap work
  retained state O(S + W)

Experimental sequence ring:
  O(1) sequence-slot bookkeeping per accepted observation
  O(W) initial slot allocation
  inherited JSON parsing O(B) and session tracking assumptions remain
```

These are operation-complexity arguments, **not** worst-case wall-clock
deadlines or field-system performance guarantees.

The H20 migration decision stays **KEEP PRODUCTION HEAP, pending target
evidence**, unless repeatable Pi measurements and correctness checks
justify a separate reviewed migration PR. Before such a migration, review
RAM/RSS, behavior under low traffic, replay equivalence, the fixed ring
allocation, and H13/H14 white-box heap tests.

A GitHub Actions benchmark should never be relabelled as a Raspberry Pi run.
For fair Pi comparisons, capture repeated independent runs under recorded
load, power and temperature conditions, check `tracked_repository_clean`,
keep the raw reports, and avoid interpreting timing slopes as proof of
asymptotic complexity.

## Acceptance for this tooling PR

- Unit tests for quick capture, integrity verification and data tampering pass.
- The full GitHub CI matrix passes.
- No production monitor behavior is changed.
- Target-device timings and memory remain explicitly unverified.
- Issue #69 remains open until target evidence and a documented decision
  are available.

Related: [H14](COMPLEXITY_H14.md),
[H16](COMPLEXITY_H16.md), [H17](COMPLEXITY_H17.md),
[H18](COMPLEXITY_H18.md), [H19](COMPLEXITY_H19.md),
and [H20 issue](https://github.com/n0711/ROS3-Limassol/issues/69).
