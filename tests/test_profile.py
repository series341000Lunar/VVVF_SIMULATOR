from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vvvf.model import DriveState, ModulationMode
from vvvf.profile import ProfileError, load_profile


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class ProfileTests(unittest.TestCase):
    def test_research_profile_loads_and_is_unverified(self) -> None:
        profile = load_profile(PROFILE_PATH)
        self.assertEqual(profile.schema_version, 2)
        self.assertEqual(profile.name, "Toshiba MCK01C Research")
        self.assertFalse(profile.verified)
        self.assertEqual(
            profile.evidence_level, "observed_from_third_party_recreation"
        )
        self.assertIn("NOT VERIFIED MANUFACTURER", profile.data_notice)

    def test_powering_region_selection_and_half_open_boundaries(self) -> None:
        cases = [
            (0.0, ModulationMode.ASYNC_PWM, 365.0, None),
            (8.4, ModulationMode.ASYNC_PWM, 365.0, None),
            (8.5, ModulationMode.SYNC_PULSE, None, 27),
            (8.6, ModulationMode.SYNC_PULSE, None, 27),
            (15.9, ModulationMode.SYNC_PULSE, None, 27),
            (16.0, ModulationMode.SYNC_PULSE, None, 15),
            (16.1, ModulationMode.SYNC_PULSE, None, 15),
            (29.9, ModulationMode.SYNC_PULSE, None, 15),
            (30.1, ModulationMode.SYNC_PULSE, None, 9),
            (47.9, ModulationMode.SYNC_PULSE, None, 9),
            (48.1, ModulationMode.SYNC_PULSE, None, 5),
            (59.9, ModulationMode.SYNC_PULSE, None, 5),
            (60.1, ModulationMode.SYNC_PULSE, None, 3),
            (72.9, ModulationMode.SYNC_PULSE, None, 3),
            (73.1, ModulationMode.SYNC_PULSE, None, 1),
            (106.8, ModulationMode.SYNC_PULSE, None, 1),
        ]
        profile = load_profile(PROFILE_PATH)
        for frequency, mode, carrier, pulse in cases:
            with self.subTest(control_frequency_hz=frequency):
                region = profile.region_for_control_frequency(frequency)
                self.assertEqual(
                    (region.mode, region.carrier_frequency_hz, region.pulse_count),
                    (mode, carrier, pulse),
                )

    def test_braking_region_selection(self) -> None:
        cases = [
            (15.9, 27),
            (16.1, 15),
            (29.9, 15),
            (30.1, 9),
            (49.9, 9),
            (50.1, 5),
            (73.9, 5),
            (74.1, 3),
            (99.9, 3),
            (100.1, 1),
        ]
        profile = load_profile(PROFILE_PATH)
        for frequency, pulse in cases:
            with self.subTest(control_frequency_hz=frequency):
                region = profile.region_for_control_frequency(
                    frequency, DriveState.BRAKING
                )
                self.assertEqual(region.pulse_count, pulse)

    def test_invalid_json_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "broken.json"
            profile_path.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "Invalid JSON"):
                load_profile(profile_path)

    def test_profile_rejects_control_frequency_gaps(self) -> None:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        data["powering"]["regions"][1]["control_frequency_start_hz"] = 8.6
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "gap.json"
            profile_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "ordered and contiguous"):
                load_profile(profile_path)

    def test_unknown_future_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "future.json"
            profile_path.write_text('{"schema_version": 99}', encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "Unsupported profile schema_version 99"):
                load_profile(profile_path)

    def test_mk1_profile_is_normalized_without_speed_based_engine_selection(self) -> None:
        legacy = {
            "name": "Legacy",
            "verified": False,
            "description": "Legacy test profile",
            "data_notice": "PLACEHOLDER",
            "motor_frequency_model": {
                "type": "linear_scale",
                "electrical_hz_per_kmh": 1.0,
            },
            "maximum_modulation_index": 0.9,
            "powering": [
                {"speed_start": 0.0, "speed_end": 10.0, "mode": "ASYNC_PWM", "carrier_hz": 400.0},
                {"speed_start": 10.0, "speed_end": 20.0, "mode": "ONE_PULSE", "pulse_count": 1},
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "legacy.json"
            profile_path.write_text(json.dumps(legacy), encoding="utf-8")
            profile = load_profile(profile_path)
            self.assertEqual(profile.schema_version, 1)
            self.assertEqual(profile.region_for_speed(10.0).mode, ModulationMode.ONE_PULSE)
            self.assertEqual(
                profile.region_for_control_frequency(10.0).mode,
                ModulationMode.ONE_PULSE,
            )


if __name__ == "__main__":
    unittest.main()
