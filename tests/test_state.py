from __future__ import annotations

import unittest
from pathlib import Path

from vvvf.profile import load_profile
from vvvf.state import SimulationState


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class StateTests(unittest.TestCase):
    def test_speed_frequency_and_modulation_are_derived_outside_ui(self) -> None:
        state = SimulationState(load_profile(PROFILE_PATH))
        snapshot = state.set_controls(speed_kmh=42.3, throttle_percent=65)
        self.assertAlmostEqual(snapshot.electrical_frequency_hz, 42.3 * 0.9)
        self.assertEqual(
            snapshot.fundamental_frequency_hz, snapshot.electrical_frequency_hz
        )
        self.assertEqual(snapshot.mode, "SYNC_PULSE")
        self.assertEqual(snapshot.pulse_count, 15)
        self.assertAlmostEqual(snapshot.modulation_index, 0.65 * 0.95)

    def test_coast_disables_modulation_without_erasing_speed(self) -> None:
        state = SimulationState(load_profile(PROFILE_PATH))
        snapshot = state.set_controls(
            speed_kmh=80.0, throttle_percent=100, direction="COAST"
        )
        self.assertEqual(snapshot.speed_kmh, 80.0)
        self.assertEqual(snapshot.electrical_frequency_hz, 72.0)
        self.assertEqual(snapshot.mode, "COAST")
        self.assertEqual(snapshot.modulation_index, 0.0)
        self.assertIsNone(snapshot.carrier_hz)
        self.assertIsNone(snapshot.pulse_count)


if __name__ == "__main__":
    unittest.main()
