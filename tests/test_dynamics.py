from __future__ import annotations

import math
import unittest
from pathlib import Path

from vvvf.dynamics import DriveDynamics
from vvvf.model import DriveState, InputMode
from vvvf.profile import load_profile
from vvvf.state import SimulationState


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class DriveDynamicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(PROFILE_PATH)
        self.assertIsNotNone(self.profile.drive_dynamics)
        self.dynamics = DriveDynamics(
            self.profile.drive_dynamics,
            self.profile.minimum_control_frequency_hz,
            self.profile.maximum_control_frequency_hz,
        )

    def test_master_command_selects_drive_state_with_dead_zone(self) -> None:
        cases = (
            (100.0, DriveState.POWERING),
            (2.01, DriveState.POWERING),
            (2.0, DriveState.COAST),
            (0.0, DriveState.COAST),
            (-2.0, DriveState.COAST),
            (-2.01, DriveState.BRAKING),
            (-100.0, DriveState.BRAKING),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(self.dynamics.set_master_command(command), expected)

    def test_full_and_partial_commands_use_profile_rates(self) -> None:
        self.dynamics.set_master_command(100.0)
        self.assertAlmostEqual(self.dynamics.advance(10.0), 30.0)
        self.dynamics.set_master_command(50.0)
        self.assertAlmostEqual(self.dynamics.advance(10.0), 45.0)
        self.dynamics.set_master_command(-100.0)
        self.assertAlmostEqual(self.dynamics.advance(10.0), 15.0)

    def test_zero_command_holds_and_limits_clamp(self) -> None:
        self.dynamics.set_frequency(40.0)
        self.dynamics.set_master_command(0.0)
        self.assertEqual(self.dynamics.advance(100.0), 40.0)
        self.dynamics.set_frequency(self.profile.maximum_control_frequency_hz)
        self.dynamics.set_master_command(100.0)
        self.assertEqual(
            self.dynamics.advance(10.0), self.profile.maximum_control_frequency_hz
        )
        self.dynamics.set_frequency(self.profile.minimum_control_frequency_hz)
        self.dynamics.set_master_command(-100.0)
        self.assertEqual(
            self.dynamics.advance(10.0), self.profile.minimum_control_frequency_hz
        )

    def test_non_finite_values_and_negative_time_are_rejected(self) -> None:
        for invalid in (math.nan, math.inf, -math.inf):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    self.dynamics.set_master_command(invalid)
                with self.assertRaises(ValueError):
                    self.dynamics.set_frequency(invalid)
        with self.assertRaises(ValueError):
            self.dynamics.advance(-0.01)


class DriveSimulationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = SimulationState(load_profile(PROFILE_PATH))

    def test_power_coast_brake_sequence_integrates_frequency(self) -> None:
        start = self.state.set_controls(
            input_mode=InputMode.DRIVE_SIMULATION,
            master_command=100.0,
            throttle_percent=25,
        )
        self.assertEqual(start.drive_state, DriveState.POWERING.value)
        self.assertEqual(start.throttle_percent, 100)
        powered = self.state.advance_time(10.0)
        self.assertAlmostEqual(powered.control_frequency_hz, 30.0)
        self.assertAlmostEqual(powered.vehicle_speed_kmh, 30.0 / 106.8 * 120.0)

        coast = self.state.set_controls(master_command=0.0)
        self.assertEqual(coast.drive_state, DriveState.COAST.value)
        held = self.state.advance_time(10.0)
        self.assertAlmostEqual(held.control_frequency_hz, 30.0)

        self.state.set_controls(master_command=-100.0)
        braked = self.state.advance_time(10.0)
        self.assertAlmostEqual(braked.control_frequency_hz, 0.0)
        self.assertEqual(braked.drive_state, DriveState.BRAKING.value)

    def test_entering_drive_simulation_preserves_current_frequency(self) -> None:
        self.state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=48.5,
            throttle_percent=100,
        )
        snapshot = self.state.set_controls(
            input_mode=InputMode.DRIVE_SIMULATION,
            master_command=0.0,
        )
        self.assertAlmostEqual(snapshot.control_frequency_hz, 48.5)
        self.assertAlmostEqual(snapshot.dynamic_control_frequency_hz, 48.5)
        self.assertEqual(snapshot.drive_state, DriveState.COAST.value)

    def test_drive_simulation_uses_profile_amplitude_not_command_magnitude(self) -> None:
        self.state.set_controls(
            input_mode=InputMode.DRIVE_SIMULATION,
            dynamic_control_frequency_hz=30.0,
            master_command=25.0,
            throttle_percent=5,
        )
        snapshot = self.state.snapshot()
        expected = self.state.profile.amplitude_for_control_frequency(
            30.0, DriveState.POWERING
        )
        self.assertAlmostEqual(snapshot.amplitude, expected)


if __name__ == "__main__":
    unittest.main()
