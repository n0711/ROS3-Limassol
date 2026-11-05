# SPDX-License-Identifier: Apache-2.0
"""Offline binary-symmetric-channel BER experiment with Hamming(7,4) FEC.

The channel, payloads, coding, and CRC are synthetic. No ROS dependency,
network transport, physical radio, or actuation is involved. Results are not
measurements of link BER or guarantees of delivery on deployed systems.
"""

import argparse
import json
import math
import random
import zlib

REPORT_VERSION = 1
MAX_MESSAGE_BYTES = 250_000


def encode_nibble(value):
    """Encode a four-bit nibble using even-parity Hamming(7,4)."""
    if type(value) is not int or not 0 <= value <= 15:
        raise ValueError("nibble must be an integer in [0, 15]")
    bits = [0] * 8  # Hamming positions 1..7; parity at 1, 2, 4.
    bits[3], bits[5], bits[6], bits[7] = (
        (value >> 3) & 1, (value >> 2) & 1, (value >> 1) & 1, value & 1
    )
    for parity in (1, 2, 4):
        bits[parity] = sum(bits[i] for i in range(1, 8)
                           if i != parity and (i & parity)) % 2
    return sum(bits[i] << (7 - i) for i in range(1, 8))


def decode_codeword(word):
    """Attempt single-bit correction; multiple errors may miscorrect."""
    if type(word) is not int or not 0 <= word < 128:
        raise ValueError("codeword must be an integer in [0, 127]")
    bits = [0] + [(word >> (7 - i)) & 1 for i in range(1, 8)]
    syndrome = 0
    for i in range(1, 8):
        if bits[i]:
            syndrome ^= i
    if syndrome:
        bits[syndrome] ^= 1
    value = (bits[3] << 3) | (bits[5] << 2) | (bits[6] << 1) | bits[7]
    return value, bool(syndrome)


def _bits_from_bytes(data):
    return [((byte >> shift) & 1) for byte in data for shift in range(7, -1, -1)]


def _bytes_from_bits(bits):
    if len(bits) % 8:
        raise ValueError("bit length must be a multiple of 8")
    return bytes(sum(bits[i + j] << (7 - j) for j in range(8))
                 for i in range(0, len(bits), 8))


def _encode(data, scheme):
    if scheme == "uncoded":
        return _bits_from_bytes(data)
    if scheme != "hamming74":
        raise ValueError("unknown coding scheme")
    bits = []
    for byte in data:
        for nibble in (byte >> 4, byte & 15):
            word = encode_nibble(nibble)
            bits.extend((word >> shift) & 1 for shift in range(6, -1, -1))
    return bits


def _decode(bits, scheme):
    if scheme == "uncoded":
        return _bytes_from_bits(bits), 0
    if scheme != "hamming74" or len(bits) % 14:
        raise ValueError("invalid coded stream")
    nibbles = []
    correction_attempts = 0
    for start in range(0, len(bits), 7):
        word = sum(bits[start + k] << (6 - k) for k in range(7))
        decoded, attempted = decode_codeword(word)
        nibbles.append(decoded)
        correction_attempts += attempted
    return bytes((nibbles[i] << 4) | nibbles[i + 1]
                 for i in range(0, len(nibbles), 2)), correction_attempts


def _channel(bits, probability, rng):
    received = []
    errors = 0
    for bit in bits:
        corrupted = rng.random() < probability
        received.append(bit ^ corrupted)
        errors += corrupted
    return received, errors


def _measure(payloads, scheme, probability, seed):
    rng = random.Random(f"{seed}:{scheme}")
    stats = {
        "frames": len(payloads), "wire_bits": 0, "channel_bit_errors": 0,
        "payload_bits": 0, "payload_bit_errors": 0,
        "crc_pass_frames": 0, "crc_fail_frames": 0,
        "correct_frames": 0, "undetected_corrupted_frames": 0,
        "correction_attempts": 0,
    }
    for payload in payloads:
        checksum = zlib.crc32(payload).to_bytes(4, "big")
        encoded = _encode(payload + checksum, scheme)
        received, raw_errors = _channel(encoded, probability, rng)
        decoded, attempts = _decode(received, scheme)
        output, received_crc = decoded[:-4], int.from_bytes(decoded[-4:], "big")
        crc_ok = zlib.crc32(output) == received_crc
        correct = output == payload
        stats["wire_bits"] += len(encoded)
        stats["channel_bit_errors"] += raw_errors
        stats["payload_bits"] += len(payload) * 8
        stats["payload_bit_errors"] += sum((a ^ b).bit_count()
                                            for a, b in zip(payload, output))
        stats["crc_pass_frames"] += crc_ok
        stats["crc_fail_frames"] += not crc_ok
        stats["correct_frames"] += correct
        stats["undetected_corrupted_frames"] += crc_ok and not correct
        stats["correction_attempts"] += attempts
    stats["measured_channel_ber"] = stats["channel_bit_errors"] / stats["wire_bits"]
    stats["residual_payload_ber"] = stats["payload_bit_errors"] / stats["payload_bits"]
    stats["frame_error_rate"] = 1 - stats["correct_frames"] / stats["frames"]
    stats["crc_pass_fraction"] = stats["crc_pass_frames"] / stats["frames"]
    stats["wire_bits_per_payload_bit"] = stats["wire_bits"] / stats["payload_bits"]
    stats["verified_goodput_fraction"] = (
        (stats["crc_pass_frames"] - stats["undetected_corrupted_frames"])
        * (stats["payload_bits"] // stats["frames"]) / stats["wire_bits"]
    )
    return stats


def run_experiment(probability=0.01, payload_bytes=32, frames=200, seed=7):
    """Compare two code rates on identical random payloads, distinct BSC draws."""
    if (type(probability) not in (int, float) or not math.isfinite(probability)
            or not 0 <= probability <= 1):
        raise ValueError("probability must be a finite value in [0, 1]")
    if type(payload_bytes) is not int or not 1 <= payload_bytes <= 4096:
        raise ValueError("payload_bytes must be an integer in [1, 4096]")
    if type(frames) is not int or not 1 <= frames <= 10000:
        raise ValueError("frames must be an integer in [1, 10000]")
    if (frames * (payload_bytes + 4)) > MAX_MESSAGE_BYTES:
        raise ValueError("experiment exceeds the bounded message budget")
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("seed must be a nonnegative 63-bit integer")
    source = random.Random(seed)
    payloads = [source.randbytes(payload_bytes) for _ in range(frames)]
    schemes = {name: _measure(payloads, name, probability, seed)
               for name in ("uncoded", "hamming74")}
    return {
        "report_version": REPORT_VERSION,
        "channel": "synthetic independent bit-flip (binary symmetric channel)",
        "flip_probability": probability,
        "seed": seed, "frames": frames, "payload_bytes": payload_bytes,
        "crc": "CRC-32 included in transmitted data, checked after decoding",
        "schemes": schemes,
        "interpretation": (
            "Residual payload BER is measured after decoding. The raw channel "
            "BER is not reduced by FEC. CRC failure rejects corrupted frames; "
            "CRC is not error correction, and a CRC pass is not proof of a "
            "correct payload. Hamming(7,4) corrects one bit per codeword and "
            "may miscorrect multiple errors. Coding increases wire bits. "
            "This is synthetic evidence, not radio/vehicle validation."
        ),
    }


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--probability", type=float, default=0.01)
    parser.add_argument("--payload-bytes", type=int, default=32)
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    options = parser.parse_args(args)
    try:
        report = run_experiment(options.probability, options.payload_bytes,
                                options.frames, options.seed)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
