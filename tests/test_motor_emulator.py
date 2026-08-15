from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from vvvf.model import ModulationMode
from vvvf.modulation import VVVFModulator
from vvvf.motor_emulator import (
    MotorAcousticEmulator,
    MotorEmulatorConfig,
    normalized_phase_voltage_abc,
)
from vvvf.profile import load_profile


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class PhaseVoltageTests(unittest.TestCase):
    def test_common_mode_is_removed_from_three_phase_switching(self) -> None:
        switching = np.array(
            [[1.0, 1.0, -1.0], [1.0, -1.0, -1.0], [-1.0, -1.0, 1.0]]
        )
        phase_voltage = normalized_phase_voltage_abc(switching)
        self.assertTrue(np.isfinite(phase_voltage).all())
        np.testing.assert_allclose(np.sum(phase_voltage, axis=0), 0.0, atol=1e-12)
        self.assertGreater(np.count_nonzero(np.diff(phase_voltage, axis=1)), 0)

    def test_waveform_block_exposes_normalized_phase_voltage(self) -> None:
        block = VVVFModulator().generate(
            4800,
            control_frequency_hz=5.0,
            mode=ModulationMode.ASYNC_PWM,
            carrier_frequency_hz=365.0,
            amplitude=0.5,
            advance_phase=False,
        )
        expected = normalized_phase_voltage_abc(block.switching)
        np.testing.assert_array_equal(block.phase_voltage_abc, expected)
        np.testing.assert_allclose(
            np.sum(block.phase_voltage_abc, axis=0), 0.0, atol=1e-12
        )

    def test_zero_amplitude_async_phase_voltage_does_not_run_away(self) -> None:
        block = VVVFModulator().generate(
            4800,
            control_frequency_hz=0.0,
            mode=ModulationMode.ASYNC_PWM,
            carrier_frequency_hz=365.0,
            amplitude=0.0,
            advance_phase=False,
        )
        self.assertTrue(np.isfinite(block.phase_voltage_abc).all())
        self.assertEqual(float(np.max(np.abs(block.phase_voltage_abc))), 0.0)

    def test_invalid_switching_shape_or_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalized_phase_voltage_abc(np.zeros((2, 10)))
        invalid = np.zeros((3, 10))
        invalid[0, 0] = np.nan
        with self.assertRaises(ValueError):
            normalized_phase_voltage_abc(invalid)


class ElectricalMagneticProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(PROFILE_PATH)
        self.config = MotorEmulatorConfig.from_mapping(self.profile.motor_acoustics)

    def test_current_flux_and_force_are_finite_and_balanced(self) -> None:
        waveform = VVVFModulator().generate(
            9600,
            control_frequency_hz=10.0,
            mode=ModulationMode.SYNC_PULSE,
            pulse_count=27,
            amplitude=0.2,
            advance_phase=False,
        )
        block = MotorAcousticEmulator(self.config).process_proxies(
            waveform.phase_voltage_abc
        )
        for values in (
            block.phase_current_abc,
            block.flux_abc,
            block.flux_alpha_beta,
            block.force_excitation,
        ):
            self.assertTrue(np.isfinite(values).all())
        np.testing.assert_allclose(
            np.sum(block.phase_current_abc, axis=0), 0.0, atol=1e-10
        )
        np.testing.assert_allclose(np.sum(block.flux_abc, axis=0), 0.0, atol=1e-10)
        self.assertGreater(float(np.std(block.force_excitation)), 1e-6)

    def test_split_blocks_match_one_long_block(self) -> None:
        waveform = VVVFModulator().generate(
            12000,
            control_frequency_hz=30.0,
            mode=ModulationMode.SYNC_PULSE,
            pulse_count=9,
            amplitude=0.4,
            advance_phase=False,
        )
        complete = MotorAcousticEmulator(self.config).process_proxies(
            waveform.phase_voltage_abc
        )
        split_emulator = MotorAcousticEmulator(self.config)
        left = split_emulator.process_proxies(waveform.phase_voltage_abc[:, :5000])
        right = split_emulator.process_proxies(waveform.phase_voltage_abc[:, 5000:])
        for whole, parts in (
            (complete.phase_current_abc, (left.phase_current_abc, right.phase_current_abc)),
            (complete.flux_abc, (left.flux_abc, right.flux_abc)),
            (
                complete.flux_alpha_beta,
                (left.flux_alpha_beta, right.flux_alpha_beta),
            ),
            (
                complete.force_excitation,
                (left.force_excitation, right.force_excitation),
            ),
        ):
            np.testing.assert_allclose(whole, np.concatenate(parts, axis=-1), atol=1e-12)

    def test_current_decays_when_phase_voltage_is_removed(self) -> None:
        emulator = MotorAcousticEmulator(self.config)
        voltage = np.repeat(
            np.array([[1.0], [-0.5], [-0.5]], dtype=np.float64), 4800, axis=1
        )
        energized = emulator.process_proxies(voltage)
        zero = np.zeros_like(voltage)
        decayed = energized
        for _ in range(10):
            decayed = emulator.process_proxies(zero)
        self.assertGreater(float(np.max(np.abs(energized.phase_current_abc))), 0.1)
        self.assertLess(float(np.max(np.abs(decayed.phase_current_abc))), 1e-8)

    def test_flux_and_force_remain_bounded_during_long_processing(self) -> None:
        modulator = VVVFModulator()
        emulator = MotorAcousticEmulator(self.config)
        maximum_flux = 0.0
        maximum_force = 0.0
        for _ in range(200):
            waveform = modulator.generate(
                2400,
                control_frequency_hz=40.0,
                mode=ModulationMode.SYNC_PULSE,
                pulse_count=9,
                amplitude=0.5,
            )
            block = emulator.process_proxies(waveform.phase_voltage_abc)
            maximum_flux = max(maximum_flux, float(np.max(np.abs(block.flux_abc))))
            maximum_force = max(
                maximum_force, float(np.max(np.abs(block.force_excitation)))
            )
        self.assertLess(maximum_flux, 2.0)
        self.assertLess(maximum_force, 2.0)

    def test_force_highpass_removes_steady_dc_component(self) -> None:
        emulator = MotorAcousticEmulator(self.config)
        voltage = np.repeat(
            np.array([[1.0], [-0.5], [-0.5]], dtype=np.float64), 4800, axis=1
        )
        result = emulator.process_proxies(voltage)
        for _ in range(10):
            result = emulator.process_proxies(voltage)
        self.assertLess(float(np.sqrt(np.mean(np.square(result.force_excitation)))), 1e-6)

    def _render_motor_block(self, frequency: float):
        region = self.profile.region_for_control_frequency(frequency)
        amplitude = self.profile.amplitude_for_control_frequency(frequency)
        modulator = VVVFModulator()
        emulator = MotorAcousticEmulator(self.config)
        emulator.set_structural_resonances(self.profile.motor_acoustics)
        result = None
        for _ in range(10):
            waveform = modulator.generate(
                4800,
                control_frequency_hz=frequency,
                mode=region.mode,
                carrier_frequency_hz=region.carrier_frequency_hz,
                pulse_count=region.pulse_count,
                amplitude=amplitude,
            )
            result = emulator.process(
                waveform.phase_voltage_abc, waveform.excitation
            )
        self.assertIsNotNone(result)
        return result

    def test_motor_force_is_primary_above_low_async_region(self) -> None:
        result = self._render_motor_block(30.0)
        force_rms = float(
            np.sqrt(np.mean(np.square(result.motor_force_component)))
        )
        leakage_rms = float(
            np.sqrt(np.mean(np.square(result.switching_leakage_component)))
        )
        self.assertGreater(force_rms, leakage_rms * 2.0)

    def test_structural_resonances_change_force_output(self) -> None:
        frequency = 30.0
        region = self.profile.region_for_control_frequency(frequency)
        amplitude = self.profile.amplitude_for_control_frequency(frequency)
        waveform = VVVFModulator().generate(
            9600,
            control_frequency_hz=frequency,
            mode=region.mode,
            pulse_count=region.pulse_count,
            amplitude=amplitude,
            advance_phase=False,
        )
        dry = MotorAcousticEmulator(self.config).process(
            waveform.phase_voltage_abc, waveform.excitation
        )
        resonant_emulator = MotorAcousticEmulator(self.config)
        resonant_emulator.set_structural_resonances(self.profile.motor_acoustics)
        resonant = resonant_emulator.process(
            waveform.phase_voltage_abc, waveform.excitation
        )
        self.assertFalse(np.allclose(dry.acoustic_output, resonant.acoustic_output))

    def test_all_profile_pulse_modes_produce_distinct_motor_output(self) -> None:
        outputs = [
            self._render_motor_block(frequency).acoustic_output
            for frequency in (5.0, 10.0, 20.0, 40.0, 50.0, 65.0, 75.0)
        ]
        for left, right in zip(outputs, outputs[1:]):
            self.assertFalse(np.allclose(left, right))

    def test_async_output_retains_365_hz_tonal_energy(self) -> None:
        output = self._render_motor_block(5.0).acoustic_output
        spectrum = np.abs(np.fft.rfft(output * np.hanning(len(output))))
        frequencies = np.fft.rfftfreq(len(output), d=1.0 / 48_000.0)
        carrier_band = spectrum[(frequencies >= 350.0) & (frequencies <= 380.0)]
        comparison_band = spectrum[
            (frequencies >= 100.0) & (frequencies <= 2000.0)
        ]
        self.assertGreater(float(np.max(carrier_band)), float(np.median(comparison_band)))


if __name__ == "__main__":
    unittest.main()
