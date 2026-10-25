# ROS3 Rust core (experimental)

Transport-independent Rust implementation of the existing telemetry-v1 validator
and receiver-arrival monitor, with a streaming JSONL replay command and optional
HMAC-SHA256 authenticated envelopes. This is an additional core, not a replacement
for ROS 2 discovery, DDS, drivers, executors, tools, or its security infrastructure.
No speed, real-time, or superiority claim has been established.

## Build and replay

Install stable Rust, then from the repository root:

```sh
cargo test --manifest-path robotics/ros3_core/Cargo.toml
cargo build --release --manifest-path robotics/ros3_core/Cargo.toml
cd robotics/ros3_limassol
python -m ros3_limassol.demo --record run.jsonl
../ros3_core/target/release/ros3-core run.jsonl --robot-id usv01 --stale-after 1.0
```

The command emits one JSON status per observation, including null silence ticks.
It consumes the existing version-1 recording format and receiver-relative clock;
it does not wait in wall time, subscribe to ROS, send commands, or run a live watchdog.
An invalid recording envelope, backwards clock, oversized line, or observation
limit violation exits nonzero. Invalid telemetry increments `rejected` and does
not refresh liveness. Output before a later input error is a partial replay.

Core API:

```rust
use ros3_core::LinkMonitor;
let mut monitor = LinkMonitor::new("usv01", 1.0, 128, None).unwrap();
// Application supplies monotonic receiver-relative seconds.
let before = monitor.snapshot(0.0).unwrap(); // WAITING
// monitor.ingest(raw_json, arrival_s)?;
let later = monitor.snapshot(1.0).unwrap();
```

`HEALTHY` means a valid arrival within the timeout. It does not prove sensor
freshness, navigation correctness, or vehicle safety. Sessions are bounded at
construction (1..4096); new sessions fail closed at capacity while the active
session can continue. Restart clears replay history.

## Authenticated mode

`AuthKey::new(Vec<u8>)` accepts 32..4096 raw bytes. Provision an independent random
32-byte key per robot through a private out-of-band channel. Do not put the key
in source, telemetry, command-line arguments, browser configuration, or recordings.
Example private key creation on Unix:

```sh
umask 077
python -c 'import secrets; open("usv01.ros3-key", "xb").write(secrets.token_bytes(32))'
```

The raw bytes are used exactly; this is not a hex/password file. The CLI reads at
most 4097 bytes, rejects invalid lengths, and on Unix rejects group/other access.
On Windows restrict the file ACL to the service account. Never use test keys in
operation. There is no secure-memory erasure or key-management service in this crate.

The producer uses `key.sign(telemetry_json)`. The receiver constructs
`LinkMonitor::new("usv01", 1.0, 128, Some(key))`. Keyed monitors accept only verified
envelopes; there is no unsigned fallback. The CLI selects this mode with
`--key-file /private/usv01.ros3-key` when replaying a recording containing envelopes.

Wire envelope (separate from telemetry-v1):

```json
{"auth_version":1,"payload":"<exact telemetry JSON text>","mac_hex":"<64 lowercase hex characters>"}
```

MAC input is the bytes `ROS3-Limassol/telemetry-hmac/v1`, one zero byte, then the
exact UTF-8 payload bytes. HMAC-SHA256 verification uses the library's
constant-time tag comparison. Reformatting the inner JSON invalidates the tag.
Unknown/duplicate fields, wrong versions and malformed tags are rejected.
Both unsigned telemetry and the entire signed envelope are bounded to 4096 bytes,
so signed messages have less available inner-payload space. `sign()` enforces this.

Verification happens before changing session, sequence or arrival state. Replayed
valid envelopes are rejected using the same session/sequence rules. This provides
shared-key origin/integrity checks, not encryption or individual publisher identity.
Every holder of a shared key can forge messages. Replay history is process-local;
an old signed session can be accepted after restart. An unobserved old message
cannot be distinguished from a newly sent one. There is no timestamp-freshness,
persistent epoch, handshake, key-ID/rotation protocol or DoS protection.

The existing Python ROS publisher, observer and live recorder do **not** implement
this envelope. Their behavior remains unchanged. Use an application integration
that signs before publication and verifies before monitoring; do not point the
unsigned Python monitor at signed traffic and assume authentication works.

## Validation

```sh
cargo fmt --manifest-path robotics/ros3_core/Cargo.toml --check
cargo clippy --manifest-path robotics/ros3_core/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path robotics/ros3_core/Cargo.toml
cargo build --manifest-path robotics/ros3_core/Cargo.toml
python robotics/ros3_core/tests/parity.py robotics/ros3_core/target/debug/ros3-core
```

The differential test compares every status to the Python monitor for a blackout,
silence, duplicate and malformed packet. It also signs the same trace independently
in Python to verify cross-language MAC compatibility. Tests cover timeout boundaries,
recovery, clock regression, session retirement/capacity, tampering, wrong keys,
unsigned downgrade, strict schemas and bounded input. CI runs these checks.

Next integration milestones: a signed live transport adapter with recorder support;
persistent replay epochs and key rotation; measured throughput/latency/memory on
identical recordings and target hardware; then controlled ROS 2 transport comparisons.
ROS 2 remains the supported transport; this crate can become a focused improvement
for intermittently connected telemetry only after these measurements and field tests.
