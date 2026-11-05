import contextlib
import io
import json
import unittest

from ros3_limassol.ber import (decode_codeword, encode_nibble, main,
                               run_experiment)


class HammingTests(unittest.TestCase):
    def test_all_nibbles_round_trip(self):
        self.assertEqual(encode_nibble(0), 0)
        self.assertEqual(encode_nibble(15), 127)
        for nibble in range(16):
            self.assertEqual(decode_codeword(encode_nibble(nibble)), (nibble, False))

    def test_all_single_bit_errors_are_correctable(self):
        for nibble in range(16):
            encoded = encode_nibble(nibble)
            for bit in range(7):
                with self.subTest(nibble=nibble, bit=bit):
                    self.assertEqual(decode_codeword(encoded ^ (1 << bit)),
                                     (nibble, True))

    def test_invalid_codewords_are_rejected(self):
        for value in (-1, 16, True, 1.5):
            with self.assertRaises(ValueError):
                encode_nibble(value)
        for value in (-1, 128, False, 1.5):
            with self.assertRaises(ValueError):
                decode_codeword(value)


class ExperimentTests(unittest.TestCase):
    def test_clean_channel_has_zero_ber_and_full_delivery(self):
        report = run_experiment(0, payload_bytes=3, frames=5, seed=1)
        uncoded, coded = (report["schemes"][name] for name in ("uncoded", "hamming74"))
        self.assertEqual(uncoded["wire_bits"], 5 * (3 + 4) * 8)
        self.assertEqual(coded["wire_bits"], 5 * (3 + 4) * 14)
        for result in (uncoded, coded):
            self.assertEqual(result["residual_payload_ber"], 0)
            self.assertEqual(result["crc_pass_frames"], 5)
            self.assertEqual(result["correct_frames"], 5)
            self.assertEqual(result["crc_fail_frames"], 0)

    def test_coding_reduces_residual_ber_in_seeded_low_error_channel(self):
        report = run_experiment(0.01, payload_bytes=16, frames=256, seed=7)
        uncoded, coded = (report["schemes"][name] for name in ("uncoded", "hamming74"))
        self.assertGreater(uncoded["residual_payload_ber"], 0)
        self.assertLess(coded["residual_payload_ber"], uncoded["residual_payload_ber"])
        self.assertGreater(coded["crc_pass_frames"], uncoded["crc_pass_frames"])
        self.assertEqual(coded["wire_bits"], uncoded["wire_bits"] * 7 // 4)
        self.assertEqual(coded["payload_bits"], uncoded["payload_bits"])

    def test_no_coding_scheme_guarantees_recovery_on_total_corruption(self):
        report = run_experiment(1, payload_bytes=8, frames=3)
        for stats in report["schemes"].values():
            self.assertEqual(stats["measured_channel_ber"], 1)
            self.assertEqual(stats["residual_payload_ber"], 1)
            self.assertEqual(stats["correct_frames"], 0)

    def test_seeded_results_are_repeatable(self):
        self.assertEqual(run_experiment(.02, 4, 20, 42),
                         run_experiment(.02, 4, 20, 42))
        self.assertNotEqual(run_experiment(.02, 4, 20, 42)["schemes"],
                            run_experiment(.02, 4, 20, 43)["schemes"])

    def test_invalid_configuration_is_rejected(self):
        for kwargs in ({"probability": float("nan")}, {"probability": -0.01},
                       {"probability": True}, {"probability": 1.01},
                       {"frames": 0}, {"frames": True},
                       {"payload_bytes": 0}, {"payload_bytes": 4097},
                       {"frames": 10000, "payload_bytes": 4096},
                       {"seed": -1}, {"seed": 2**63}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run_experiment(**kwargs)

    def test_cli_reports_json_and_rejects_nan(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--probability", "0", "--frames", "2", "--payload-bytes", "1"])
        report = json.loads(out.getvalue())
        self.assertEqual(report["schemes"]["hamming74"]["correct_frames"], 2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--probability", "nan"])


if __name__ == "__main__":
    unittest.main()
