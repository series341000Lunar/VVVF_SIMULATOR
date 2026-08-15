from __future__ import annotations

import unittest

import numpy as np

from vvvf.model import ModulationMode
from vvvf.modulation import VVVFModulator


class ModulationTests(unittest.TestCase):
    def test_three_phase_references_are_offset_by_120_degrees(self) -> None:
        block = VVVFModulator().generate(
            32,
            control_frequency_hz=10.0,
            mode=ModulationMode.SYNC_PULSE,
            pulse_count=9,
            amplitude=1.0,
            advance_phase=False,
        )
        self.assertAlmostEqual(block.references[0, 0], 0.0, places=12)
        self.assertAlmostEqual(block.references[1, 0], -np.sqrt(3) / 2, places=12)
        self.assertAlmostEqual(block.references[2, 0], np.sqrt(3) / 2, places=12)

    def test_async_365_hz_produces_switching(self) -> None:
        block = VVVFModulator().generate(
            4800,
            control_frequency_hz=5.0,
            mode=ModulationMode.ASYNC_PWM,
            carrier_frequency_hz=365.0,
            amplitude=0.6,
            advance_phase=False,
        )
        self.assertEqual(block.effective_switching_frequency_hz, 365.0)
        self.assertGreater(np.count_nonzero(np.diff(block.switching[0])), 20)

    def test_27_pulse_changes_real_switching_pattern(self) -> None:
        modulator = VVVFModulator()
        pulse_27 = modulator.generate(
            4800,
            control_frequency_hz=10.0,
            mode=ModulationMode.SYNC_PULSE,
            pulse_count=27,
            amplitude=0.8,
            advance_phase=False,
        )
        pulse_15 = modulator.generate(
            4800,
            control_frequency_hz=10.0,
            mode=ModulationMode.SYNC_PULSE,
            pulse_count=15,
            amplitude=0.8,
            advance_phase=False,
        )
        transitions_27 = np.count_nonzero(np.diff(pulse_27.switching[0]))
        transitions_15 = np.count_nonzero(np.diff(pulse_15.switching[0]))
        self.assertGreater(transitions_27, transitions_15)
        self.assertFalse(np.array_equal(pulse_27.switching, pulse_15.switching))

    def test_one_pulse_has_fewer_transitions_than_three_pulse(self) -> None:
        modulator = VVVFModulator()
        one = modulator.generate(
            4800,
            control_frequency_hz=10.0,
            mode=ModulationMode.SYNC_PULSE,
            pulse_count=1,
            amplitude=1.0,
            advance_phase=False,
        )
        three = modulator.generate(
            4800,
            control_frequency_hz=10.0,
            mode=ModulationMode.SYNC_PULSE,
            pulse_count=3,
            amplitude=1.0,
            advance_phase=False,
        )
        self.assertLess(
            np.count_nonzero(np.diff(one.switching[0])),
            np.count_nonzero(np.diff(three.switching[0])),
        )


if __name__ == "__main__":
    unittest.main()
