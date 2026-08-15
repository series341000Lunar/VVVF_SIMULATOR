from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vvvf.profile import ProfileError, load_profile


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class ProfileTests(unittest.TestCase):
    def test_research_profile_loads_and_is_unverified(self) -> None:
        profile = load_profile(PROFILE_PATH)
        self.assertEqual(profile.name, "Toshiba MCK01C Research")
        self.assertFalse(profile.verified)
        self.assertIn("NOT VERIFIED MCK01C DATA", profile.data_notice)

    def test_speed_region_selection(self) -> None:
        cases = [
            (0.0, "ASYNC_PWM", 450.0, None),
            (19.9, "ASYNC_PWM", 450.0, None),
            (20.0, "ASYNC_PWM", 600.0, None),
            (20.1, "ASYNC_PWM", 600.0, None),
            (35.0, "SYNC_PULSE", None, 15),
            (50.0, "SYNC_PULSE", None, 9),
            (70.0, "ONE_PULSE", None, 1),
            (120.0, "ONE_PULSE", None, 1),
        ]
        profile = load_profile(PROFILE_PATH)
        for speed, mode, carrier, pulse in cases:
            with self.subTest(speed=speed):
                region = profile.region_for_speed(speed)
                self.assertEqual(
                    (region.mode, region.carrier_hz, region.pulse_count),
                    (mode, carrier, pulse),
                )

    def test_invalid_json_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "broken.json"
            profile_path.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "Invalid JSON"):
                load_profile(profile_path)

    def test_profile_rejects_speed_gaps(self) -> None:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        data["powering"][1]["speed_start"] = 20.5
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "gap.json"
            profile_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "ordered and contiguous"):
                load_profile(profile_path)


if __name__ == "__main__":
    unittest.main()
