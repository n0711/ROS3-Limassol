# CI/CD configuration and schema

GitHub is the canonical repository: [n0711/ROS3-Limassol](https://github.com/n0711/ROS3-Limassol).
The existing [GitHub Actions workflows](../.github/workflows/) are the primary automated checks.
The root [`.gitlab-ci.yml`](../.gitlab-ci.yml) is an **optional GitLab mirror pipeline**.
It does not run on GitHub and does not imply a GitLab mirror or runner already exists.

## GitLab schema

The CI file starts with a `yaml-language-server` schema comment pointing to
[GitLab's official CI JSON schema](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/assets/javascripts/editor/schema/ci.json).
The same association is included in [VS Code workspace settings](../.vscode/settings.json).
With a YAML language server/extension installed this enables editor diagnostics and completion.
These checks do not guarantee that a runner can execute the jobs.

For a GitLab mirror, run **Build > Pipeline editor > Validate** (CI Lint) before
enabling pipelines. A GitLab project and usable Docker runner are required.
See [GitLab CI Lint](https://docs.gitlab.com/ci/yaml/lint/).
The `master` schema URL is upstream-maintained and may evolve; GitLab CI Lint
is the authoritative project-context check.

## Coverage

| Component | GitHub workflow | Optional GitLab job |
| --- | --- | --- |
| Python telemetry core (3.10, 3.12), package and replay | `ros3-ci.yml` | `ros3-python-310`, `ros3-python-312` |
| Rust telemetry core, lint, tests, Python parity | `ros3-rust.yml` | `ros3-rust` |
| ROS 2 Humble / Ubuntu 22.04 | `ros3-ci.yml` | `ros2-humble` |
| ROS 2 Jazzy / Ubuntu 24.04 | `ros3-ci.yml` | `ros2-jazzy` |
| LearnTwin/backend Python tests | `academic-import.yml` (focused tests) | `academic-python` (full pytest) |
| Rust academic store tests | `academic-import.yml` | `academic-rust` |
| LearnTwin frontend tests, lint, build | `academic-import.yml` | `learntwin-frontend` |

The GitLab jobs use container images; they do not deploy software, access secrets,
publish artifacts, or attempt vehicle control. GitLab and GitHub job triggers differ:
compare observed outcomes rather than treating a configured job as a passing test.

## Validation before performance claims

Successful CI verifies software behavior in automated environments, not actual
robotic hardware or real-world communications reliability. ROS graph, synthetic
blackout/recovery, and recording/replay tests must not be represented as field
validation. See [the experiment validation record](../robotics/ros3_limassol/docs/VALIDATION.md).
