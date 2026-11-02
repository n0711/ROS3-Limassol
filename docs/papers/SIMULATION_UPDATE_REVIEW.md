# Simulation update: author review and evidence record

Date: 31 October 2026. References: [#42](https://github.com/n0711/ROS3-Limassol/issues/42),
[#33](https://github.com/n0711/ROS3-Limassol/issues/33),
[#38](https://github.com/n0711/ROS3-Limassol/pull/38).

The author requested continuation after reviewing the decision record. This
authorizes a draft PR; it does not establish final approval, submission,
publication, an archive DOI, or new experimental results. No software behaviour,
defaults, schema, recording format or licence is changed.

## P1--P5 applied to the review draft

| Decision | Draft treatment | Still for the author |
| --- | --- | --- |
| P1: revision or companion | Revise `arxiv/main.tex`, keeping historical sections 1--7 intact. | Approve the wording and publication container. No existing arXiv submission is verified. |
| P2: section or appendix | A dated section after the historical conclusion keeps original section numbering and experimental text intact; supplementary SITL tables are in an appendix. | Approve this placement, which differs from the outline's suggested insertion after verification. |
| P3: sweep or repository only | Include six representative synthetic rows and cite the full pinned sweep. State seeds, duration, source rate, tick, timeout, detection reference, missed short outages and already-STALE cases. | Approve selection; these are transcribed reported numbers, not rerun data. |
| P4: archive or summaries | Require an external archive of original run bundles; disclose that only scenarios and aggregates are available in the repository. | Supply the original artifacts or authorize newly dated replacement runs; approve archive destination. Do not commit recordings. |
| P5: after #33 or physical results | #33 is closed and #38 merged. A simulation report can precede physical tests, with the audit gap explicit. | Final submission timing, article licence and evidence sufficiency. No merge or submission performed here. |

## Evidence sources and exact scope

Source snapshot: `65da1ea17d2a1de68e24a8f6e3120bbfd2fd1e11`.

- `robotics/ros3_limassol/docs/VALIDATION.md`: original clean SITL outages,
  20-run impairment comparison and 30 October relay-log validation follow-up.
- `robotics/ros3_limassol/docs/IMPAIRMENT.md`: full synthetic sweep, three-way
  live/observed-timing/nominal comparison, provenance requirements and uncertainty.
- `robotics/ros3_limassol/docs/MAVLINK.md`: mapping, withheld samples, arrival-order
  numbering, no send path, and current 3 s default versus historical 1 s runs.
- `robotics/ros3_limassol/docs/SITL.md`: reproducibility commands and setup.
- `docs/papers/ARXIV.md`: not submitted; no arXiv ID established.

The clean-SITL 1.206--1.257 s interval is measured from the last **accepted
arrival**, not outage onset. It is consistent with the conditional [1.0, 1.5] s
bound for timeout 1.0 s and assumed maximum evaluation gap 0.5 s; no hard
scheduling guarantee follows from four observations or a nominal timer period.

The 20-run comparison uses a different tick (0.1 s), five seeds per profile,
4 Hz source, one timeout (1.0 s), 300 s per run and sample-aligned fates. The
nominal model can misstate short-outage detection and recovery because of
source phase and timing variation. Arrival-order bridge numbering means the
bridge comparison cannot establish source-order rejection behaviour.

## Raw-evidence audit still outstanding

- [ ] Locate each original run's exact scenario plus seed, relay JSONL log,
      bridge JSONL recording, JSON comparison report and tool/version identifiers.
- [ ] Retain originals and hashes together, including the relay's genuine final
      summary. Never reconstruct a missing summary to satisfy the checker.
- [ ] Re-score with current `tools/compare_impairment.py`; check scenario identity,
      sample indices and summary consistency, plus `alignment.covers_scenario`
      and relay exit conditions. A consistent summary alone proves no full run.
- [ ] Reconcile each run and every aggregate with the historical tables. Record
      discrepancies rather than tuning them away.
- [ ] Archive original bundles outside git with a stable identifier, then add
      its verified citation. No archive was created or located in this work.
- [ ] If originals are unavailable, retain the reported-results qualification;
      replacement experiments need new dates and provenance and cannot restore
      the original raw record.

## What #33 does not settle

Closing #33 and merging #38 establishes that its implementation and reported
simulation results entered the repository. It does not establish independent
reproduction or resolve the missing raw-recording audit. The later completeness
tests are synthetic software checks, not a repeat of those SITL experiments.

Radio, real network, companion-computer deployment, field operation, physical
dynamics, PX4 and signed/multi-vehicle SITL coverage are outside these reported
experiments. No inference of vehicle safety, autonomy, measurement capture age,
position accuracy or research novelty is justified. Physical validation is a
separate future evidence requirement, not a prerequisite for honestly reporting
the limited simulation results.

## Review and validation

Observed locally on Linux with Python 3.12.14:

- Package unittest suite: 175 discovered, 168 passed, seven ROS-dependent skips
  (`rclpy` absent).
- Deterministic demo: WAITING/HEALTHY/STALE/HEALTHY at 0.0/0.0/2.9/5.0 s;
  51 accepted, zero rejected. Compileall and `git diff --check` passed.
- Repeated XeLaTeX build: ten pages, references resolved, no overfull boxes;
  every rendered page visually inspected.
- Source packager: archive contains exactly `main.tex`, byte-identical to the
  edited source; its compiled PDF is temporary review output, not committed.
- Original sections 1--7 compared byte-for-byte against the base commit.

No new SITL, ROS graph, radio, hardware or field experiment is claimed. The
historical PDF files are unchanged; build the revised `arxiv/main.tex` to review.
