"""Safe real-time audio synthesis and sounddevice stream lifecycle."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import signal

from .loudness import (
    LoudnessCalibrationPoint,
    LoudnessCompensationConfig,
    MonitorLoudnessCompensator,
)
from .model import ModulationMode
from .modulation import VVVFModulator
from .profile import VVVFProfile
from .state import SimulationSnapshot


FloatArray = NDArray[np.float64]


class MotorAcousticModel:
    """Small resonant filter bank; it is not an electromagnetic FEM model."""

    def __init__(self, profile: VVVFProfile, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._filters: list[tuple[FloatArray, FloatArray, FloatArray, float]] = []
        resonances = profile.motor_acoustics.get("resonances", [])
        if not isinstance(resonances, list):
            resonances = []
        for resonance in resonances:
            if not isinstance(resonance, dict):
                continue
            frequency = float(
                resonance.get("frequency_hz", resonance.get("frequency", 0.0))
            )
            gain = float(resonance.get("gain", 1.0))
            q = float(resonance.get("q", 4.0))
            if not all(math.isfinite(value) for value in (frequency, gain, q)):
                continue
            if not 20.0 <= frequency < sample_rate / 2.0 or gain < 0 or q <= 0:
                continue
            b, a = signal.iirpeak(frequency, q, fs=sample_rate)
            zi = np.zeros(max(len(a), len(b)) - 1, dtype=np.float64)
            self._filters.append((b, a, zi, gain))

    def process(self, excitation: FloatArray) -> FloatArray:
        output = 0.12 * excitation
        if not self._filters:
            return output
        resonance_sum = np.zeros_like(excitation)
        total_gain = 0.0
        updated: list[tuple[FloatArray, FloatArray, FloatArray, float]] = []
        for b, a, zi, gain in self._filters:
            filtered, next_zi = signal.lfilter(b, a, excitation, zi=zi)
            resonance_sum += gain * filtered
            total_gain += gain
            updated.append((b, a, next_zi, gain))
        self._filters = updated
        return output + resonance_sum / max(total_gain, 1.0)


class AudioSynthesizer:
    """Block synthesizer with conservative volume, smoothing, and limiting."""

    _calibration_cache: dict[tuple[object, ...], tuple[LoudnessCalibrationPoint, ...]] = {}

    def __init__(
        self,
        profile: VVVFProfile,
        *,
        sample_rate: int = 48_000,
        master_volume: float = 0.2,
    ) -> None:
        self.sample_rate = sample_rate
        self.modulator = VVVFModulator(sample_rate)
        self.acoustics = MotorAcousticModel(profile, sample_rate)
        loudness_config = LoudnessCompensationConfig.from_mapping(
            profile.motor_acoustics
        )
        calibration = self._calibrate_legacy_model(
            profile, sample_rate, loudness_config
        )
        self.loudness_compensator = MonitorLoudnessCompensator(
            loudness_config, calibration, sample_rate
        )
        self._master_volume = 0.2
        self._last_sample = 0.0
        self.set_master_volume(master_volume)

    @property
    def master_volume(self) -> float:
        return self._master_volume

    @property
    def loudness_compensation_enabled(self) -> bool:
        return self.loudness_compensator.enabled

    @property
    def monitor_gain_db(self) -> float:
        return self.loudness_compensator.current_gain_db

    @classmethod
    def _calibrate_legacy_model(
        cls,
        profile: VVVFProfile,
        sample_rate: int,
        config: LoudnessCompensationConfig,
    ) -> tuple[LoudnessCalibrationPoint, ...]:
        cache_key = (
            "LEGACY_SWITCHING",
            sample_rate,
            profile.minimum_control_frequency_hz,
            profile.maximum_control_frequency_hz,
            repr(profile.patterns),
            repr(profile.motor_acoustics),
        )
        cached = cls._calibration_cache.get(cache_key)
        if cached is not None:
            return cached
        minimum = profile.minimum_control_frequency_hz
        maximum = profile.maximum_control_frequency_hz
        frequencies = np.arange(
            minimum,
            maximum + config.calibration_step_hz * 0.5,
            config.calibration_step_hz,
            dtype=np.float64,
        )
        if not len(frequencies) or frequencies[-1] < maximum:
            frequencies = np.append(frequencies, maximum)
        else:
            frequencies[-1] = min(frequencies[-1], maximum)
        warmup_samples = max(
            int(round(config.calibration_warmup_seconds * sample_rate)), 1
        )
        measure_samples = max(
            int(round(config.calibration_measure_seconds * sample_rate)), 1
        )
        points: list[LoudnessCalibrationPoint] = []
        for frequency in frequencies:
            amplitude = profile.amplitude_for_control_frequency(float(frequency))
            region = profile.region_for_control_frequency(float(frequency))
            if amplitude <= config.minimum_profile_amplitude or frequency <= 0:
                expected_rms = 0.0
            else:
                modulator = VVVFModulator(sample_rate)
                acoustics = MotorAcousticModel(profile, sample_rate)
                warmup = modulator.generate(
                    warmup_samples,
                    control_frequency_hz=float(frequency),
                    mode=region.mode,
                    carrier_frequency_hz=region.carrier_frequency_hz,
                    pulse_count=region.pulse_count,
                    amplitude=amplitude,
                )
                acoustics.process(warmup.excitation)
                measured = modulator.generate(
                    measure_samples,
                    control_frequency_hz=float(frequency),
                    mode=region.mode,
                    carrier_frequency_hz=region.carrier_frequency_hz,
                    pulse_count=region.pulse_count,
                    amplitude=amplitude,
                )
                raw_audio = acoustics.process(measured.excitation)
                limiter_preview = np.tanh(raw_audio * 1.6)
                expected_rms = float(
                    np.sqrt(np.mean(np.square(limiter_preview, dtype=np.float64)))
                )
            points.append(
                LoudnessCalibrationPoint(
                    float(frequency),
                    region.mode.value,
                    region.pulse_count,
                    expected_rms,
                )
            )
        result = tuple(points)
        cls._calibration_cache[cache_key] = result
        return result

    def set_master_volume(self, volume: float) -> None:
        converted = float(volume)
        if not math.isfinite(converted):
            raise ValueError("master volume must be finite")
        self._master_volume = min(max(converted, 0.0), 1.0)

    def set_loudness_compensation(self, enabled: bool) -> None:
        self.loudness_compensator.set_enabled(enabled)

    def synthesize(
        self, snapshot: SimulationSnapshot, num_samples: int
    ) -> NDArray[np.float32]:
        if snapshot.mode == "COAST" or snapshot.amplitude <= 0.0:
            target = np.zeros(num_samples, dtype=np.float64)
        else:
            block = self.modulator.generate(
                num_samples,
                control_frequency_hz=snapshot.control_frequency_hz,
                mode=ModulationMode(snapshot.mode),
                carrier_frequency_hz=snapshot.carrier_frequency_hz,
                pulse_count=snapshot.pulse_count,
                amplitude=snapshot.amplitude,
            )
            target = self.acoustics.process(block.excitation)
        target = self.loudness_compensator.process(
            target,
            control_frequency_hz=snapshot.control_frequency_hz,
            mode=snapshot.mode,
            pulse_count=snapshot.pulse_count,
            profile_amplitude=snapshot.amplitude,
        )
        limited = np.tanh(target * 1.6) * self._master_volume
        smoothing_samples = min(64, num_samples)
        if smoothing_samples:
            blend = np.linspace(0.0, 1.0, smoothing_samples, endpoint=True)
            limited[:smoothing_samples] = self._last_sample + blend * (
                limited[:smoothing_samples] - self._last_sample
            )
        self._last_sample = float(limited[-1]) if num_samples else self._last_sample
        return np.clip(limited, -0.95, 0.95).astype(np.float32)


class AudioOutput:
    """Own and safely release a sounddevice output stream."""

    def __init__(
        self,
        profile: VVVFProfile,
        snapshot_provider: Callable[[], SimulationSnapshot],
        *,
        sample_rate: int = 48_000,
        block_size: int = 512,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.synthesizer = AudioSynthesizer(profile, sample_rate=sample_rate)
        self._snapshot_provider = snapshot_provider
        self._stream_factory = stream_factory
        self._stream: Any | None = None
        self._lock = threading.RLock()
        self.state = "STOPPED"

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def set_master_volume(self, volume: float) -> None:
        with self._lock:
            self.synthesizer.set_master_volume(volume)

    def set_loudness_compensation(self, enabled: bool) -> None:
        with self._lock:
            self.synthesizer.set_loudness_compensation(enabled)

    @property
    def loudness_compensation_enabled(self) -> bool:
        with self._lock:
            return self.synthesizer.loudness_compensation_enabled

    @property
    def monitor_gain_db(self) -> float:
        with self._lock:
            return self.synthesizer.monitor_gain_db

    def _callback(
        self, outdata: NDArray[np.float32], frames: int, _time: Any, status: Any
    ) -> None:
        if status:
            self.state = f"RUNNING (device status: {status})"
        try:
            with self._lock:
                audio = self.synthesizer.synthesize(
                    self._snapshot_provider(), frames
                )
            if outdata.ndim == 1:
                outdata[:] = audio
            else:
                outdata[:, 0] = audio
                for channel in range(1, outdata.shape[1]):
                    outdata[:, channel] = audio
        except Exception:
            outdata.fill(0.0)
            self.state = "ERROR IN AUDIO CALLBACK"

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            if self._stream_factory is None:
                import sounddevice as sound_device

                factory = sound_device.OutputStream
            else:
                factory = self._stream_factory
            stream: Any | None = None
            try:
                stream = factory(
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    channels=1,
                    dtype="float32",
                    callback=self._callback,
                )
                stream.start()
            except Exception as exc:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                self.state = f"ERROR: {exc}"
                raise
            self._stream = stream
            self.state = "RUNNING"

    def stop(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()
            self.state = "STOPPED"
