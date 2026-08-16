from __future__ import annotations

import unittest
from pathlib import Path

from vvvf.profile import load_profile
from vvvf.scenario import FullCycleScenario, ScenarioPhase, ScenarioRunner


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class ScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(PROFILE_PATH)
        self.scenario = FullCycleScenario.from_profile(self.profile)

    def test_durations_are_derived_from_profile(self) -> None:
        self.assertAlmostEqual(self.scenario.powering_duration_s, 106.8 / 3.0)
        self.assertAlmostEqual(self.scenario.coast_duration_s, 4.0)
        self.assertAlmostEqual(self.scenario.braking_duration_s, 106.8 / 3.0)
        self.assertAlmostEqual(self.scenario.total_duration_s, 75.2)

    def test_runner_reaches_max_holds_during_coast_and_returns_to_zero(self) -> None:
        runner = ScenarioRunner(self.profile, self.scenario)
        self.assertEqual(runner.phase, ScenarioPhase.POWERING)
        self.assertAlmostEqual(runner.snapshot().control_frequency_hz, 0.0)

        runner.advance(self.scenario.powering_duration_s)
        self.assertEqual(runner.phase, ScenarioPhase.COAST)
        self.assertAlmostEqual(runner.snapshot().control_frequency_hz, 106.8)
        runner.advance(self.scenario.coast_duration_s / 2.0)
        self.assertEqual(runner.snapshot().pulse_count, 3)
        self.assertAlmostEqual(runner.snapshot().control_frequency_hz, 106.8)
        runner.advance(self.scenario.coast_duration_s / 2.0)
        self.assertEqual(runner.phase, ScenarioPhase.BRAKING)
        runner.advance(self.scenario.braking_duration_s)
        self.assertTrue(runner.complete)
        self.assertAlmostEqual(runner.snapshot().control_frequency_hz, 0.0)


if __name__ == "__main__":
    unittest.main()
