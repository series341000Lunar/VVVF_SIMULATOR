from __future__ import annotations

import math
import unittest
from pathlib import Path

from vvvf.model import DriveState
from vvvf.profile import ProfileError, load_profile


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class AmplitudeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(PROFILE_PATH)

    def test_powering_keyframes_are_exact(self) -> None:
        expected = {0.0: 0.0, 22.7: 0.243, 48.1: 0.516, 48.5: 0.659, 106.8: 1.0}
        for frequency, amplitude in expected.items():
            with self.subTest(frequency=frequency):
                self.assertAlmostEqual(
                    self.profile.amplitude_for_control_frequency(frequency), amplitude
                )

    def test_linear_interpolation(self) -> None:
        midpoint = (22.7 + 37.9) / 2.0
        expected = (0.243 + 0.406) / 2.0
        self.assertAlmostEqual(
            self.profile.amplitude_for_control_frequency(midpoint), expected
        )

    def test_powering_discontinuity_is_not_smoothed(self) -> None:
        just_before_step = self.profile.amplitude_for_control_frequency(48.49)
        at_step = self.profile.amplitude_for_control_frequency(48.5)
        self.assertAlmostEqual(just_before_step, 0.516)
        self.assertAlmostEqual(at_step, 0.659)
        self.assertGreater(at_step - just_before_step, 0.14)

    def test_braking_low_frequency_cutoff(self) -> None:
        self.assertEqual(
            self.profile.amplitude_for_control_frequency(7.3, DriveState.BRAKING),
            0.0,
        )
        self.assertAlmostEqual(
            self.profile.amplitude_for_control_frequency(7.5, DriveState.BRAKING),
            0.063,
        )

    def test_control_frequency_is_clamped_to_106_8(self) -> None:
        self.assertEqual(self.profile.clamp_control_frequency(999.0), 106.8)
        self.assertEqual(self.profile.amplitude_for_control_frequency(999.0), 1.0)

    def test_nan_and_inf_are_rejected(self) -> None:
        for invalid in (math.nan, math.inf, -math.inf):
            with self.subTest(value=invalid):
                with self.assertRaises(ProfileError):
                    self.profile.clamp_control_frequency(invalid)


if __name__ == "__main__":
    unittest.main()
