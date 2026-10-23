from dataclasses import replace
import json
import unittest

from ros3_limassol.telemetry import MAX_PAYLOAD_BYTES, Telemetry


def packet(**changes):
    sample = Telemetry(1, "usv01", "boot_1", 0, 123, 34.67, 33.04, 90.0, 0.6, 85.0)
    return replace(sample, **changes)


class TelemetryTests(unittest.TestCase):
    def test_round_trip_preserves_fields(self):
        sample = packet()
        self.assertEqual(Telemetry.from_json(sample.to_json()), sample)

    def test_v1_rejects_missing_extra_and_duplicate_keys(self):
        payload = json.loads(packet().to_json())
        del payload["battery_pct"]
        with self.assertRaises(ValueError):
            Telemetry.from_json(json.dumps(payload))
        payload = json.loads(packet().to_json())
        payload["extra"] = 1
        with self.assertRaises(ValueError):
            Telemetry.from_json(json.dumps(payload))
        duplicate = packet().to_json().replace('"schema_version":1',
                                               '"schema_version":1,"schema_version":1')
        with self.assertRaises(ValueError):
            Telemetry.from_json(duplicate)

    def test_invalid_numbers_and_units_are_rejected(self):
        cases = {
            "schema_version": [True, 1.0, 2],
            "sequence": [True, -1, 0.5, 2**63],
            "timestamp_ns": [False, -1, 2**63],
            "latitude_deg": [91, -91, float("nan"), float("inf"), True, "34"],
            "longitude_deg": [181, -181],
            "heading_deg": [-1, 360],
            "speed_m_s": [-1, 101, 10**400],
            "battery_pct": [-1, 101],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaises(ValueError):
                        packet(**{field: value})

    def test_identifier_rules(self):
        for value in ("", "USV", "usv/01", "a" * 33, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                packet(robot_id=value)
        for value in ("", "a" * 65, "boot/1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                packet(session_id=value)

    def test_malformed_oversized_and_nonstandard_json(self):
        for raw in ("{", "[]", "null", "x" * (MAX_PAYLOAD_BYTES + 1),
                    '["' + "é" * 2500 + '"]', "[" * 2000 + "]" * 2000,
                    '{"x": NaN}', '{"x": Infinity}', "\ud800", b"{}"):
            with self.subTest(raw=repr(raw[:40])), self.assertRaises(ValueError):
                Telemetry.from_json(raw)
