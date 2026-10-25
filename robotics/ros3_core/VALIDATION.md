# Validation evidence

Executed on 25 October 2026 in the development container:

- Rust stable 1.99.1: `cargo test --locked` — 6 integration tests passed.
- `cargo clippy --locked --all-targets -- -D warnings` — passed.
- `cargo fmt --check` — passed after formatting.
- Debug binary built successfully.
- `tests/parity.py`: 73 unsigned states and 73 independently Python-signed states
  exactly matched the existing Python monitor; oversized recording line rejected.
- Existing Python robotics suite: 42 passed, 3 ROS graph tests skipped because
  rclpy is unavailable locally. No live DDS/ROS result is claimed here.
- Frontend suite: 18 passed, including JSON-header and multipart authentication
  regressions. ESLint and Vite production build passed.

These are functional and interoperability checks, not a security audit,
performance benchmark, real-time guarantee, or evidence of superiority over ROS 2.
The signed envelope has not been connected to the existing ROS adapter.

Reproduction commands and protocol limitations are in README.md. CI independently
runs Rust formatting, lint, tests, build and Python differential replay.
