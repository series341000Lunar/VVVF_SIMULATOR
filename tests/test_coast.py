from __future__ import annotations

import unittest
from pathlib import Path

from vvvf.model import DriveState, InputMode
from vvvf.profile import load_profile
from vvvf.state import SimulationState


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class CoastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = SimulationState(load_profile(PROFILE_PATH))
        self.state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=106.8,
            throttle_percent=100,
        )

    def test_coast_holds_frequency_uses_three_pulse_and_decays(self) -> None:
        start = self.state.set_controls(drive_state=DriveState.COAST)
        self.assertEqual(start.control_frequency_hz, 106.8)
        self.assertEqual(start.pulse_count, 3)
        self.assertAlmostEqual(start.amplitude, 0.827)

        self.state.set_controls(direct_control_frequency_hz=20.0)
        midpoint = self.state.advance_time(2.0)
        self.assertEqual(midpoint.control_frequency_hz, 106.8)
        self.assertAlmostEqual(midpoint.amplitude, 0.444)

        finished = self.state.advance_time(2.0)
        self.assertEqual(finished.amplitude, 0.0)

    def test_coast_decay_time_is_marked_as_unverified_tuning(self) -> None:
        coast = self.state.profile.coast
        self.assertEqual(coast.decay_seconds, 4.0)
        self.assertIn("NOT VERIFIED", coast.decay_notice)

    def test_invalid_time_delta_is_rejected(self) -> None:
        self.state.set_controls(drive_state=DriveState.COAST)
        with self.assertRaises(ValueError):
            self.state.advance_time(-0.01)


if __name__ == "__main__":
    unittest.main()
