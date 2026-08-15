"""Output-only loudness calibration and realtime gain smoothing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class LoudnessCompensationConfig:
    enabled_default: bool
    target_rms_dbfs: float
    minimum_compensation_db: float
    maximum_compensation_db: float
    minimum_profile_amplitude: float
    calibration_step_hz: float
    calibration_warmup_seconds: float
    calibration_measure_seconds: float
    curve_smoothing_hz: float
    attack_ms: float
    release_ms: float
    data_notice: str

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "LoudnessCompensationConfig":
        section = mapping.get("monitor_loudness", {})
        if not isinstance(section, dict):
            raise ValueError("motor_acoustics.monitor_loudness must be an object")

        def finite(key: str, default: float) -> float:
            value = section.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"monitor_loudness.{key} must be a number")
            converted = float(value)
            if not math.isfinite(converted):
                raise ValueError(f"monitor_loudness.{key} must be finite")
            return converted

        enabled = section.get("enabled_default", True)
        if not isinstance(enabled, bool):
            raise ValueError("monitor_loudness.enabled_default must be true or false")
        notice = section.get(
            "data_notice", "SIMULATOR MONITOR TUNING — NOT VEHICLE CONTROL DATA"
        )
        if not isinstance(notice, str) or not notice.strip():
            raise ValueError("monitor_loudness.data_notice must be a non-empty string")
        config = cls(
            enabled_default=enabled,
            target_rms_dbfs=finite("target_rms_dbfs", -20.0),
            minimum_compensation_db=finite("minimum_compensation_db", -6.0),
            maximum_compensation_db=finite("maximum_compensation_db", 18.0),
            minimum_profile_amplitude=finite("minimum_profile_amplitude", 0.005),
            calibration_step_hz=finite("calibration_step_hz", 1.0),
            calibration_warmup_seconds=finite(
                "calibration_warmup_seconds", 0.15
            ),
            calibration_measure_seconds=finite(
                "calibration_measure_seconds", 0.35
            ),
            curve_smoothing_hz=finite("curve_smoothing_hz", 2.0),
            attack_ms=finite("attack_ms", 150.0),
            release_ms=finite("release_ms", 500.0),
            data_notice=notice.strip(),
        )
        if config.minimum_compensation_db > config.maximum_compensation_db:
            raise ValueError("monitor loudness gain limits must be increasing")
        if not 0 <= config.minimum_profile_amplitude <= 1:
            raise ValueError("minimum_profile_amplitude must be in [0, 1]")
        positive = (
            config.calibration_step_hz,
            config.calibration_warmup_seconds,
            config.calibration_measure_seconds,
            config.attack_ms,
            config.release_ms,
        )
        if any(value <= 0 for value in positive) or config.curve_smoothing_hz < 0:
            raise ValueError("monitor loudness timing and calibration values are invalid")
        return config


@dataclass(frozen=True, slots=True)
class LoudnessCalibrationPoint:
    control_frequency_hz: float
    mode: str
    pulse_count: int | None
    expected_rms: float


class MonitorLoudnessCompensator:
    """Apply a calibrated frequency/mode gain without tracking live RMS."""

    def __init__(
        self,
        config: LoudnessCompensationConfig,
        calibration_points: tuple[LoudnessCalibrationPoint, ...],
        sample_rate: int,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.config = config
        self.sample_rate = int(sample_rate)
        self.enabled = config.enabled_default
        self._current_gain_linear = 1.0
        self._global_curve = self._build_curve(calibration_points)
        grouped: dict[tuple[str, int | None], list[LoudnessCalibrationPoint]] = {}
        for point in calibration_points:
            grouped.setdefault((point.mode, point.pulse_count), []).append(point)
        self._mode_curves = {
            key: self._build_curve(tuple(points)) for key, points in grouped.items()
        }

    @property
    def current_gain_db(self) -> float:
        return 20.0 * math.log10(max(self._current_gain_linear, 1e-12))

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def reset(self) -> None:
        self._current_gain_linear = 1.0

    def _build_curve(
        self, points: tuple[LoudnessCalibrationPoint, ...]
    ) -> tuple[FloatArray, FloatArray]:
        usable = sorted(
            (
                point
                for point in points
                if math.isfinite(point.expected_rms) and point.expected_rms > 0
            ),
            key=lambda point: point.control_frequency_hz,
        )
        if not usable:
            return np.array([0.0]), np.array([0.0])
        frequencies = np.array(
            [point.control_frequency_hz for point in usable], dtype=np.float64
        )
        measured_db = 20.0 * np.log10(
            np.maximum(
                np.array([point.expected_rms for point in usable], dtype=np.float64),
                1e-12,
            )
        )
        gains = np.clip(
            self.config.target_rms_dbfs - measured_db,
            self.config.minimum_compensation_db,
            self.config.maximum_compensation_db,
        )
        if len(gains) > 2 and self.config.curve_smoothing_hz > 0:
            typical_step = float(np.median(np.diff(frequencies)))
            radius = max(
                int(round(self.config.curve_smoothing_hz / max(typical_step, 1e-9))),
                1,
            )
            kernel = np.ones(2 * radius + 1, dtype=np.float64)
            kernel /= np.sum(kernel)
            padded = np.pad(gains, radius, mode="edge")
            gains = np.convolve(padded, kernel, mode="valid")
            gains = np.clip(
                gains,
                self.config.minimum_compensation_db,
                self.config.maximum_compensation_db,
            )
        return frequencies, gains

    def target_gain_db(
        self,
        control_frequency_hz: float,
        mode: str,
        pulse_count: int | None,
        profile_amplitude: float,
    ) -> float:
        values = (
            float(control_frequency_hz),
            float(profile_amplitude),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Loudness lookup values must be finite")
        if (
            not self.enabled
            or control_frequency_hz <= 0
            or profile_amplitude <= self.config.minimum_profile_amplitude
        ):
            return 0.0
        frequencies, gains = self._mode_curves.get(
            (str(mode), pulse_count), self._global_curve
        )
        gain = float(np.interp(control_frequency_hz, frequencies, gains))
        return min(
            max(gain, self.config.minimum_compensation_db),
            self.config.maximum_compensation_db,
        )

    def process(
        self,
        audio: FloatArray,
        *,
        control_frequency_hz: float,
        mode: str,
        pulse_count: int | None,
        profile_amplitude: float,
    ) -> FloatArray:
        samples = np.asarray(audio, dtype=np.float64)
        if samples.ndim != 1:
            raise ValueError("Monitor loudness input must be one-dimensional")
        if not np.isfinite(samples).all():
            raise ValueError("Monitor loudness input must be finite")
        target_db = self.target_gain_db(
            control_frequency_hz, mode, pulse_count, profile_amplitude
        )
        target_linear = 10.0 ** (target_db / 20.0)
        if not len(samples):
            return samples.copy()
        time_constant_ms = (
            self.config.attack_ms
            if target_linear < self._current_gain_linear
            else self.config.release_ms
        )
        coefficient = math.exp(
            -1.0 / (self.sample_rate * time_constant_ms / 1000.0)
        )
        powers = np.power(coefficient, np.arange(1, len(samples) + 1))
        gain_envelope = target_linear + (
            self._current_gain_linear - target_linear
        ) * powers
        self._current_gain_linear = float(gain_envelope[-1])
        return samples * gain_envelope
