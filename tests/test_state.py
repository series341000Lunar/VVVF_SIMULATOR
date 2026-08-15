from __future__ import annotations

import unittest
from pathlib import Path

from vvvf.profile import load_profile
from vvvf.state import SimulationState


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class StateTests(unittest.TestCase):
    def test_speed_control_frequency_and_amplitude_are_derived_outside_ui(self) -> None:
        state = SimulationState(load_profile(PROFILE_PATH))
        snapshot = state.set_controls(speed_kmh=42.3, throttle_percent=65)
        self.assertAlmostEqual(snapshot.control_frequency_hz, 42.3 / 120.0 * 106.8)
        self.assertEqual(
            snapshot.fundamental_frequency_hz, snapshot.electrical_frequency_hz
        )
        self.assertEqual(snapshot.mode, "SYNC_PULSE")
        self.assertEqual(snapshot.pulse_count, 9)
        profile_amplitude = state.profile.amplitude_for_control_frequency(
            snapshot.control_frequency_hz
        )
        self.assertAlmostEqual(snapshot.modulation_index, 0.65 * profile_amplitude)

    def test_coast_holds_control_frequency_and_uses_three_pulse(self) -> None:
        state = SimulationState(load_profile(PROFILE_PATH))
        snapshot = state.set_controls(
            speed_kmh=80.0, throttle_percent=100, direction="COAST"
        )
        self.assertEqual(snapshot.speed_kmh, 80.0)
        self.assertAlmostEqual(snapshot.control_frequency_hz, 71.2)
        self.assertEqual(snapshot.mode, "SYNC_PULSE")
        self.assertEqual(snapshot.pulse_count, 3)
        self.assertGreater(snapshot.modulation_index, 0.0)
        self.assertIsNone(snapshot.carrier_hz)


if __name__ == "__main__":
    unittest.main()
