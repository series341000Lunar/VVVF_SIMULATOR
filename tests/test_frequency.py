from __future__ import annotations

import math
import unittest
from pathlib import Path

from vvvf.model import DriveState, InputMode
from vvvf.profile import load_profile
from vvvf.state import SimulationState


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class FrequencyArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(PROFILE_PATH)

    def test_virtual_speed_uses_configurable_mapper(self) -> None:
        state = SimulationState(self.profile)
        snapshot = state.set_controls(
            input_mode=InputMode.VIRTUAL_VEHICLE_SPEED,
            vehicle_speed_kmh=60.0,
            throttle_percent=100,
        )
        self.assertAlmostEqual(snapshot.control_frequency_hz, 53.4)

    def test_inverse_mapper_round_trips_control_frequency(self) -> None:
        mapper = self.profile.frequency_mapper
        for frequency in (0.0, 8.5, 53.4, 106.8):
            with self.subTest(control_frequency_hz=frequency):
                speed = mapper.unmap_control_frequency(frequency)
                self.assertAlmostEqual(mapper.map_speed(speed), frequency)

    def test_direct_frequency_bypasses_vehicle_speed(self) -> None:
        state = SimulationState(self.profile)
        snapshot = state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            vehicle_speed_kmh=120.0,
            direct_control_frequency_hz=8.6,
            throttle_percent=100,
        )
        self.assertEqual(snapshot.control_frequency_hz, 8.6)
        self.assertEqual(snapshot.pulse_count, 27)

    def test_direct_mode_disables_hysteresis_for_exact_threshold_research(self) -> None:
        state = SimulationState(self.profile)
        state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=8.49,
            throttle_percent=100,
        )
        snapshot = state.set_controls(direct_control_frequency_hz=8.5)
        self.assertEqual(snapshot.pulse_count, 27)

    def test_virtual_mode_hysteresis_prevents_boundary_chatter(self) -> None:
        state = SimulationState(self.profile)
        state.set_controls(
            input_mode=InputMode.VIRTUAL_VEHICLE_SPEED,
            vehicle_speed_kmh=8.49 / 106.8 * 120.0,
            throttle_percent=100,
        )
        held = state.set_controls(vehicle_speed_kmh=8.51 / 106.8 * 120.0)
        self.assertEqual(held.mode, "ASYNC_PWM")
        crossed = state.set_controls(vehicle_speed_kmh=8.7 / 106.8 * 120.0)
        self.assertEqual(crossed.pulse_count, 27)

    def test_braking_uses_separate_profile_table(self) -> None:
        state = SimulationState(self.profile)
        snapshot = state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=49.0,
            drive_state=DriveState.BRAKING,
            throttle_percent=100,
        )
        self.assertEqual(snapshot.pulse_count, 9)
        powering = state.set_controls(drive_state=DriveState.POWERING)
        self.assertEqual(powering.pulse_count, 5)

    def test_non_finite_direct_input_is_rejected(self) -> None:
        state = SimulationState(self.profile)
        for invalid in (math.nan, math.inf, -math.inf):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    state.set_controls(direct_control_frequency_hz=invalid)


if __name__ == "__main__":
    unittest.main()
