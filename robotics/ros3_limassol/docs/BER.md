# Offline residual BER and Hamming(7,4) experiment

`ros3_limassol.ber` is a standalone, standard-library-only demonstration of
forward error correction (FEC). It compares uncoded frames and Hamming(7,4)
encoded frames under independent synthetic bit flips. It does **not** connect
to a radio, ROS graph or MAVLink bridge, and does not send vehicle messages.

From `robotics/ros3_limassol`:

```sh
python -m ros3_limassol.ber --probability 0.01 --payload-bytes 16 --frames 256 --seed 7
python -m unittest tests.test_ber -v
```

Each frame contains random payload bytes followed by a CRC-32. Both schemes
send identical original payloads, but independently seeded bit-flip streams;
these are not paired physical-channel samples. The decoder checks the CRC of
the recovered payload. A CRC mismatch marks the frame as failed; CRC-32 is an
error detector, **not** an error corrector, and cannot guarantee detection of
every possible error. Hamming(7,4) encodes four input bits into seven channel
bits. Its syndrome can correct a single flipped bit per seven-bit codeword;
with multiple errors, syndrome correction may yield an incorrect nibble.

## Metrics

- `measured_channel_ber` = flipped on-wire bits / transmitted bits, including
  CRC and FEC bits. Coding does not change the configured channel flip rate.
- `residual_payload_ber` = wrong decoded payload bits / original payload bits,
  excluding CRC bits. This is the post-decoder BER of the experiment.
- `frame_error_rate` = frames with any decoded payload error / frames sent;
  this is measured using the known synthetic source payload, not CRC alone.
- `crc_pass_fraction` = frames passing the received CRC / frames sent. This may
  differ from payload correctness because checksum bits can also be corrupted.
- `undetected_corrupted_frames` = CRC passes despite a wrong payload.
- `correction_attempts` counts nonzero Hamming syndromes, **not** proven fixes.
- `wire_bits_per_payload_bit` includes both CRC and code-rate overhead.
- `verified_goodput_fraction` counts the payload bits of correct, CRC-passing
  frames divided by all transmitted wire bits (no retransmission).

## Reproducible synthetic example

Using Python 3.13.5, seed 7, 256 frames of 16-byte payloads and a bit-flip
probability of 0.01:

| Metric | Uncoded | Hamming(7,4) |
| --- | ---: | ---: |
| Measured channel BER | 0.0095458984 | 0.0099190848 |
| Residual payload BER | 0.0097351074 | 0.0004882812 |
| Correct decoded payloads | 78 / 256 | 247 / 256 |
| CRC-pass frames | 59 / 256 | 243 / 256 |
| Wire bits | 40,960 | 71,680 |

This one seeded experiment reduces **residual** BER by approximately 95%, at
1.75 times the transmitted bits; it does **not** reduce physical channel BER.
These figures are sampled outcomes, not theoretical guarantees or field data.

## Limits and next validation

The independent binary symmetric channel models neither fading, burst errors,
interference, synchronisation errors, buffer loss, real protocol framing,
retransmission nor varying radio modulation. Longer codewords, different error
rates and real channel traces can change the tradeoff. Frame-level FEC does not
replace rate-control or a genuine bidirectional ARQ design. Before claiming
physical-link improvement, benchmark repeated seeds across probability and
burst profiles, then validate on hardware with source and receiver bit-level
capture, packet counts, payload hashes and time/energy/overhead measurements.

The project-wide architecture permits future bidirectional communication, but
this BER experiment is deliberately an offline measuring tool rather than a
physical transport or a control path.
