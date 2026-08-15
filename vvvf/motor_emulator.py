"""Physically inspired, normalized induction-motor acoustic proxy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import signal


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class MotorEmulatorConfig:
    model: str
    default_audio_model: str
    electrical_time_constant_ms: float
    flux_time_constant_ms: float
    probe_count: int
    probe_highpass_hz: float
    probe_weights: tuple[float, ...]
    motor_force_mix: float
    switching_leakage_mix: float
    output_gain: float
    model_crossfade_ms: float
    data_notice: str

    @classmethod
    def from_mapping(
        cls, mapping: dict[str, Any], sample_rate: int = 48_000
    ) -> "MotorEmulatorConfig":
        if not isinstance(mapping, dict):
            raise ValueError("motor_acoustics must be an object")

        def section(name: str) -> dict[str, Any]:
            value = mapping.get(name, {})
            if not isinstance(value, dict):
                raise ValueError(f"motor_acoustics.{name} must be an object")
            return value

        def finite(container: dict[str, Any], key: str, default: float) -> float:
            value = container.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"motor_acoustics.{key} must be a number")
            converted = float(value)
            if not math.isfinite(converted):
                raise ValueError(f"motor_acoustics.{key} must be finite")
            return converted

        electrical = section("electrical_response")
        flux = section("flux_response")
        force = section("force_model")
        electrical_tau = finite(electrical, "time_constant_ms", 1.5)
        flux_tau = finite(flux, "time_constant_ms", 3.0)
        highpass = finite(force, "highpass_hz", 20.0)
        probe_count_raw = force.get("probe_count", 8)
        if (
            isinstance(probe_count_raw, bool)
            or not isinstance(probe_count_raw, int)
            or not 3 <= probe_count_raw <= 16
        ):
            raise ValueError("motor_acoustics.force_model.probe_count must be 3..16")
        weights_raw = force.get("probe_weights")
        if weights_raw is None:
            weights = tuple(
                1.0 + 0.08 * math.cos(index * 1.7) + 0.03 * math.sin(index * 2.3)
                for index in range(probe_count_raw)
            )
        else:
            if not isinstance(weights_raw, list) or len(weights_raw) != probe_count_raw:
                raise ValueError("probe_weights length must match probe_count")
            weights_list: list[float] = []
            for value in weights_raw:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("probe_weights must contain finite numbers")
                converted = float(value)
                if not math.isfinite(converted) or converted <= 0:
                    raise ValueError("probe_weights must contain positive finite numbers")
                weights_list.append(converted)
            weights = tuple(weights_list)
        force_mix = finite(mapping, "motor_force_mix", 0.97)
        leakage_mix = finite(mapping, "switching_leakage_mix", 0.03)
        output_gain = finite(mapping, "output_gain", 60.0)
        crossfade_ms = finite(mapping, "model_crossfade_ms", 50.0)
        model = mapping.get("model", "induction_motor_proxy")
        default_audio_model = mapping.get("default_audio_model", "MOTOR EMULATOR")
        notice = mapping.get(
            "data_notice", "SIMULATOR TUNING — NOT VERIFIED MOTOR DATA"
        )
        if model != "induction_motor_proxy":
            raise ValueError("motor_acoustics.model must be induction_motor_proxy")
        if default_audio_model not in {"LEGACY SWITCHING", "MOTOR EMULATOR"}:
            raise ValueError("motor_acoustics.default_audio_model is invalid")
        if not isinstance(notice, str) or not notice.strip():
            raise ValueError("motor_acoustics.data_notice must be a non-empty string")
        if electrical_tau <= 0 or flux_tau <= 0:
            raise ValueError("motor response time constants must be positive")
        if not 0 < highpass < sample_rate / 2:
            raise ValueError("force highpass must be between 0 Hz and Nyquist")
        if not 0 <= force_mix <= 1 or not 0 <= leakage_mix <= 1:
            raise ValueError("motor acoustic mix values must be in [0, 1]")
        if force_mix <= leakage_mix:
            raise ValueError("motor_force_mix must be greater than switching_leakage_mix")
        if output_gain <= 0 or not 10 <= crossfade_ms <= 500:
            raise ValueError("motor output gain or crossfade time is invalid")
        resonances = mapping.get("resonances", [])
        if not isinstance(resonances, list):
            raise ValueError("motor_acoustics.resonances must be an array")
        for index, resonance in enumerate(resonances):
            if not isinstance(resonance, dict):
                raise ValueError(f"motor resonance {index} must be an object")
            frequency = finite(resonance, "frequency_hz", 0.0)
            gain = finite(resonance, "gain", 1.0)
            q = finite(resonance, "q", 4.0)
            if not 20 <= frequency < sample_rate / 2 or gain < 0 or q <= 0:
                raise ValueError(f"motor resonance {index} parameters are invalid")
        return cls(
            model=model,
            default_audio_model=default_audio_model,
            electrical_time_constant_ms=electrical_tau,
            flux_time_constant_ms=flux_tau,
            probe_count=probe_count_raw,
            probe_highpass_hz=highpass,
            probe_weights=weights,
            motor_force_mix=force_mix,
            switching_leakage_mix=leakage_mix,
            output_gain=output_gain,
            model_crossfade_ms=crossfade_ms,
            data_notice=notice.strip(),
        )


@dataclass(frozen=True, slots=True)
class MotorProxyBlock:
    phase_current_abc: FloatArray
    flux_abc: FloatArray
    flux_alpha_beta: FloatArray
    force_excitation: FloatArray


@dataclass(frozen=True, slots=True)
class MotorAudioBlock:
    phase_current_abc: FloatArray
    flux_abc: FloatArray
    flux_alpha_beta: FloatArray
    force_excitation: FloatArray
    motor_force_component: FloatArray
    switching_leakage_component: FloatArray
    acoustic_output: FloatArray


class StructuralResonanceBank:
    """Reusable stateful structural modes for either acoustic model."""

    def __init__(self, mapping: dict[str, Any], sample_rate: int) -> None:
        self._filters: list[tuple[FloatArray, FloatArray, FloatArray, float]] = []
        for resonance in mapping.get("resonances", []):
            frequency = float(resonance["frequency_hz"])
            gain = float(resonance["gain"])
            q = float(resonance["q"])
            b, a = signal.iirpeak(frequency, q, fs=sample_rate)
            zi = np.zeros(max(len(a), len(b)) - 1, dtype=np.float64)
            self._filters.append((b, a, zi, gain))

    def reset(self) -> None:
        self._filters = [
            (b, a, np.zeros_like(zi), gain) for b, a, zi, gain in self._filters
        ]

    def process(self, excitation: FloatArray) -> FloatArray:
        if not self._filters:
            return np.zeros_like(excitation)
        resonance_sum = np.zeros_like(excitation)
        total_gain = 0.0
        updated: list[tuple[FloatArray, FloatArray, FloatArray, float]] = []
        for b, a, zi, gain in self._filters:
            filtered, next_zi = signal.lfilter(b, a, excitation, zi=zi)
            resonance_sum += gain * filtered
            total_gain += gain
            updated.append((b, a, next_zi, gain))
        self._filters = updated
        return resonance_sum / max(total_gain, 1.0)


class _StatefulLowPass:
    def __init__(self, time_constant_ms: float, sample_rate: int, channels: int) -> None:
        coefficient = math.exp(-1.0 / (sample_rate * time_constant_ms / 1000.0))
        self._b = np.array([1.0 - coefficient], dtype=np.float64)
        self._a = np.array([1.0, -coefficient], dtype=np.float64)
        self._zi = np.zeros((channels, 1), dtype=np.float64)

    def reset(self) -> None:
        self._zi.fill(0.0)

    def process(self, values: FloatArray) -> FloatArray:
        output = np.empty_like(values)
        for channel in range(values.shape[0]):
            output[channel], self._zi[channel] = signal.lfilter(
                self._b, self._a, values[channel], zi=self._zi[channel]
            )
        return output


class MotorAcousticEmulator:
    """Stateful electrical, magnetic, and radial-force proxy stages."""

    def __init__(
        self, config: MotorEmulatorConfig, sample_rate: int = 48_000
    ) -> None:
        if sample_rate < 8_000:
            raise ValueError("sample_rate must be at least 8000 Hz")
        self.config = config
        self.sample_rate = int(sample_rate)
        self._current_filter = _StatefulLowPass(
            config.electrical_time_constant_ms, self.sample_rate, 3
        )
        self._flux_filter = _StatefulLowPass(
            config.flux_time_constant_ms, self.sample_rate, 3
        )
        angles = np.linspace(0.0, 2.0 * np.pi, config.probe_count, endpoint=False)
        self._probe_cos = np.cos(angles)[:, np.newaxis]
        self._probe_sin = np.sin(angles)[:, np.newaxis]
        self._probe_weights = np.asarray(config.probe_weights)[:, np.newaxis]
        self._probe_weight_sum = float(np.sum(self._probe_weights))
        self._force_b, self._force_a = signal.butter(
            1, config.probe_highpass_hz, btype="highpass", fs=self.sample_rate
        )
        self._force_zi = np.zeros(
            max(len(self._force_a), len(self._force_b)) - 1, dtype=np.float64
        )
        self._resonances = StructuralResonanceBank({}, self.sample_rate)

    def set_structural_resonances(self, mapping: dict[str, Any]) -> None:
        self._resonances = StructuralResonanceBank(mapping, self.sample_rate)

    def reset(self) -> None:
        self._current_filter.reset()
        self._flux_filter.reset()
        self._force_zi.fill(0.0)
        self._resonances.reset()

    def process_proxies(self, phase_voltage_abc: FloatArray) -> MotorProxyBlock:
        voltage = np.asarray(phase_voltage_abc, dtype=np.float64)
        if voltage.ndim != 2 or voltage.shape[0] != 3:
            raise ValueError("phase_voltage_abc must have shape (3, samples)")
        if not np.isfinite(voltage).all():
            raise ValueError("phase_voltage_abc must be finite")
        current = self._current_filter.process(voltage)
        current -= np.mean(current, axis=0, keepdims=True)
        flux = self._flux_filter.process(current)
        flux -= np.mean(flux, axis=0, keepdims=True)
        flux_alpha = (2.0 / 3.0) * (
            flux[0] - 0.5 * flux[1] - 0.5 * flux[2]
        )
        flux_beta = (2.0 / 3.0) * (np.sqrt(3.0) / 2.0) * (
            flux[1] - flux[2]
        )
        flux_alpha_beta = np.vstack((flux_alpha, flux_beta))
        probe_field = (
            self._probe_cos * flux_alpha[np.newaxis, :]
            + self._probe_sin * flux_beta[np.newaxis, :]
        )
        probe_force = np.square(probe_field)
        mixed_force = np.sum(self._probe_weights * probe_force, axis=0) / max(
            self._probe_weight_sum, 1e-12
        )
        force_excitation, self._force_zi = signal.lfilter(
            self._force_b, self._force_a, mixed_force, zi=self._force_zi
        )
        return MotorProxyBlock(current, flux, flux_alpha_beta, force_excitation)

    def process(
        self, phase_voltage_abc: FloatArray, legacy_excitation: FloatArray
    ) -> MotorAudioBlock:
        legacy = np.asarray(legacy_excitation, dtype=np.float64)
        if legacy.ndim != 1 or legacy.shape[0] != phase_voltage_abc.shape[1]:
            raise ValueError("legacy_excitation must match the phase-voltage block")
        if not np.isfinite(legacy).all():
            raise ValueError("legacy_excitation must be finite")
        proxies = self.process_proxies(phase_voltage_abc)
        force_source = self.config.output_gain * proxies.force_excitation
        structured = self._resonances.process(force_source)
        motor_component = 0.15 * force_source + structured
        weighted_motor = self.config.motor_force_mix * motor_component
        weighted_leakage = self.config.switching_leakage_mix * legacy
        acoustic_output = weighted_motor + weighted_leakage
        return MotorAudioBlock(
            proxies.phase_current_abc,
            proxies.flux_abc,
            proxies.flux_alpha_beta,
            proxies.force_excitation,
            weighted_motor,
            weighted_leakage,
            acoustic_output,
        )


def normalized_phase_voltage_abc(switching: FloatArray) -> FloatArray:
    """Remove bridge common mode from three normalized switching states."""
    states = np.asarray(switching, dtype=np.float64)
    if states.ndim != 2 or states.shape[0] != 3:
        raise ValueError("switching must have shape (3, samples)")
    if not np.isfinite(states).all():
        raise ValueError("switching states must be finite")
    common_mode = np.mean(states, axis=0, keepdims=True)
    return states - common_mode
