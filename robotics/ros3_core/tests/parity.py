#!/usr/bin/env python3
"""Compare every Rust/Python state for a deterministic fault trace; verify HMAC interoperability."""
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'robotics' / 'ros3_limassol'))
from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.simulator import UsvSimulator

binary = Path(sys.argv[1]).resolve()
source = UsvSimulator(session_id='parity-session')
observations = []
for tick in range(71):
    now = tick / 10
    packet = source.sample(now, tick * 100_000_000)
    raw = packet.to_json() if packet else None
    observations.append({'record_version': 1, 'time_s': now, 'payload': raw})
    if tick == 10:
        observations.append({'record_version': 1, 'time_s': now, 'payload': raw})
    if tick == 20:
        observations.append({'record_version': 1, 'time_s': now, 'payload': '{malformed'})
reference = LinkMonitor()
expected = []
for row in observations:
    if row['payload'] is not None:
        reference.ingest(row['payload'], row['time_s'])
    expected.append(json.loads(reference.snapshot(row['time_s']).to_json()))
with tempfile.TemporaryDirectory() as folder:
    recording = Path(folder) / 'trace.jsonl'
    def run(rows, *args):
        recording.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        return subprocess.run([str(binary), str(recording), *args], capture_output=True, text=True, check=True)
    actual = [json.loads(line) for line in run(observations).stdout.splitlines()]
    assert actual == expected, 'Rust/Python state mismatch'
    # The signed format has its own version and authenticates the exact payload bytes.
    key = bytes(range(32))
    keyfile = Path(folder) / 'test.ros3-key'
    keyfile.write_bytes(key)
    keyfile.chmod(0o600)
    signed_rows = []
    for row in observations:
        payload = row['payload']
        if payload is not None:
            tag = hmac.new(key, b'ROS3-Limassol/telemetry-hmac/v1\0'+payload.encode(), hashlib.sha256).hexdigest()
            payload = json.dumps({'auth_version': 1, 'payload': payload, 'mac_hex': tag})
        signed_rows.append({**row, 'payload': payload})
    signed_actual = [json.loads(line) for line in run(signed_rows, '--key-file', str(keyfile)).stdout.splitlines()]
    assert signed_actual == expected, 'Authenticated replay differs from Python reference'
    # Bounded reader rejects overlong lines before unbounded allocation.
    recording.write_text('x' * 32769)
    assert subprocess.run([str(binary), str(recording)], capture_output=True).returncode != 0
print(f'PASS: {len(expected)} unsigned and {len(expected)} authenticated states; bounded reader rejection')
