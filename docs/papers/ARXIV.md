# arXiv preparation

Status: prepared locally, not submitted. No arXiv ID has been assigned.

Author: Charalampos Nadiotis. Initial project idea: Christos Paparistodemou
(acknowledgement, following the original manuscript; not a coauthor claim).

## Manuscript scope

The original PDF remains a historical version-0.1.0 report. `arxiv/main.tex`
preserves its experiment and adds a dated preparation note, the public GitHub
link, corrected working-directory instructions and portable TeX Live font
filenames. Version 0.3.1 results are identified separately: 45 tests discovered,
42 passed, three ROS tests skipped locally. No field results or novelty claims
have been added. The new source has an inline bibliography and no figures.

## Build and package

From the repository root, create a separate build directory and run:

```sh
mkdir -p /tmp/ros3-paper-build
xelatex -halt-on-error -output-directory=/tmp/ros3-paper-build docs/papers/arxiv/main.tex
xelatex -halt-on-error -output-directory=/tmp/ros3-paper-build docs/papers/arxiv/main.tex
python scripts/package_arxiv.py /tmp/ROS3_Limassol_arxiv_source.zip
```

The packager exclusively includes `main.tex`, and refuses to overwrite an
existing archive. Upload the ZIP, not the entire mixed-purpose repository.
Use XeLaTeX; select TeX Live 2025 when offered and review arXiv's generated PDF.
The GitHub repository is linked in the manuscript; it is not a separate arXiv
submission. No ancillary code upload is required for this preparation.

## Submission metadata

- Title: ROS3-Limassol: An OpenPELAOS Prototype for Telemetry Liveness Monitoring
- Author: Charalampos Nadiotis
- Suggested category: cs.RO (Robotics), subject to author and moderator assessment.
- Comments: Preliminary technical report; original version-0.1.0 experiment with
  a dated software-availability and validation update.
- Abstract: copy the abstract from `arxiv/main.tex` (remove TeX markup).
- DOI / journal reference: leave empty; none has been assigned.
- License: the author must choose the article distribution license during
  submission. The robotics software's Apache-2.0 license does not by itself
  select an article license.

## Remaining account steps

Sign in to the author's arXiv account, start a submission, resolve any requested
category endorsement, upload the source ZIP, inspect the processed PDF, enter
metadata and complete the submission agreement and license choice. This
preparation does not assert endorsement, acceptance, peer review or publication.
The contribution remains a preliminary implementation report; arXiv moderators
determine whether it meets their scientific-content requirements.

## Official guidance checked

- https://info.arxiv.org/help/submit/index.html
- https://info.arxiv.org/help/submit_tex.html
- https://info.arxiv.org/help/faq/texlive.html
- https://info.arxiv.org/help/endorsement.html
