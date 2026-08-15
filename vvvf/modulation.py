"""Vectorized three-phase switching synthesis in the control-frequency domain."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .model import ModulationMode


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class WaveformBlock:
    time_seconds: FloatArray
    references: FloatArray
    switching: FloatArray
    line_voltage_uv: FloatArray
    excitation: FloatArray
    effective_switching_frequency_hz: float


class VVVFModulator:
    """Generate real switching patterns without knowing vehicle speed."""

    def __init__(self, sample_rate: int = 48_000) -> None:
        if sample_rate < 8_000:
            raise ValueError("sample_rate must be at least 8000 Hz")
        self.sample_rate = int(sample_rate)
        self._fundamental_phase = 0.0
        self._async_carrier_phase = 0.0

    def reset(self) -> None:
        self._fundamental_phase = 0.0
        self._async_carrier_phase = 0.0

    def generate(
        self,
        num_samples: int,
        *,
        control_frequency_hz: float,
        mode: ModulationMode | str,
        amplitude: float,
        carrier_frequency_hz: float | None = None,
        pulse_count: int | None = None,
        advance_phase: bool = True,
    ) -> WaveformBlock:
        if not isinstance(num_samples, int) or num_samples <= 0:
            raise ValueError("num_samples must be a positive integer")
        frequency = float(control_frequency_hz)
        normalized_amplitude = float(amplitude)
        if not math.isfinite(frequency) or frequency < 0:
            raise ValueError("control_frequency_hz must be finite and non-negative")
        if not math.isfinite(normalized_amplitude) or not 0 <= normalized_amplitude <= 1:
            raise ValueError("amplitude must be finite and in [0, 1]")
        modulation_mode = ModulationMode(mode)
        time_seconds = np.arange(num_samples, dtype=np.float64) / self.sample_rate
        theta = self._fundamental_phase + 2.0 * np.pi * frequency * time_seconds
        phase_offsets = np.array([0.0, -2.0 * np.pi / 3.0, 2.0 * np.pi / 3.0])
        raw_references = np.sin(theta[np.newaxis, :] + phase_offsets[:, np.newaxis])
        references = normalized_amplitude * raw_references

        if modulation_mode is ModulationMode.ASYNC_PWM:
            if carrier_frequency_hz is None:
                raise ValueError("ASYNC_PWM requires carrier_frequency_hz")
            switching_frequency = float(carrier_frequency_hz)
            if not math.isfinite(switching_frequency) or switching_frequency <= 0:
                raise ValueError("carrier_frequency_hz must be finite and positive")
            carrier_cycles = self._async_carrier_phase + switching_frequency * time_seconds
            carrier = 2.0 * np.abs(2.0 * np.mod(carrier_cycles, 1.0) - 1.0) - 1.0
            switching = np.where(references >= carrier[np.newaxis, :], 1.0, -1.0)
        elif modulation_mode is ModulationMode.ONE_PULSE:
            switching_frequency = frequency
            switching = np.where(raw_references >= 0.0, 1.0, -1.0)
        else:
            if isinstance(pulse_count, bool) or not isinstance(pulse_count, int) or pulse_count <= 0:
                raise ValueError("SYNC_PULSE requires a positive integer pulse_count")
            switching_frequency = frequency * pulse_count
            if pulse_count == 1:
                switching = np.where(raw_references >= 0.0, 1.0, -1.0)
            else:
                synchronous_cycles = pulse_count * theta / (2.0 * np.pi)
                carrier = (
                    2.0 * np.abs(2.0 * np.mod(synchronous_cycles, 1.0) - 1.0) - 1.0
                )
                switching = np.where(references >= carrier[np.newaxis, :], 1.0, -1.0)

        # The modulation index already controls switching duty through the PWM
        # references. Bridge voltage levels remain normalized DC-bus states;
        # multiplying them by amplitude again would double-scale low-speed audio.
        line_voltage_uv = 0.5 * (switching[0] - switching[1])
        common_mode = np.mean(switching, axis=0)
        excitation = (
            0.72 * line_voltage_uv
            + 0.28
            * normalized_amplitude
            * np.diff(common_mode, prepend=common_mode[0])
        )
        if advance_phase:
            elapsed = num_samples / self.sample_rate
            self._fundamental_phase = float(
                np.mod(self._fundamental_phase + 2.0 * np.pi * frequency * elapsed, 2.0 * np.pi)
            )
            if modulation_mode is ModulationMode.ASYNC_PWM:
                self._async_carrier_phase = float(
                    np.mod(self._async_carrier_phase + switching_frequency * elapsed, 1.0)
                )
        return WaveformBlock(
            time_seconds,
            references,
            switching,
            line_voltage_uv,
            excitation,
            switching_frequency,
        )
