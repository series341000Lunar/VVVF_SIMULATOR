"""Safe real-time audio synthesis and sounddevice stream lifecycle."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .loudness import (
    LoudnessCalibrationPoint,
    LoudnessCompensationConfig,
    MonitorLoudnessCompensator,
)
from .model import AudioModel, ModulationMode
from .modulation import VVVFModulator
from .motor_emulator import (
    MotorAcousticEmulator,
    MotorEmulatorConfig,
    StructuralResonanceBank,
)
from .profile import VVVFProfile
from .state import SimulationSnapshot


FloatArray = NDArray[np.float64]


class MotorAcousticModel:
    """Legacy switching excitation plus the shared structural resonance bank."""

    def __init__(self, profile: VVVFProfile, sample_rate: int) -> None:
        self._resonances = StructuralResonanceBank(
            profile.motor_acoustics, sample_rate
        )

    def reset(self) -> None:
        self._resonances.reset()

    def process(self, excitation: FloatArray) -> FloatArray:
        output = 0.12 * excitation
        return output + self._resonances.process(excitation)


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
        self.profile = profile
        self.sample_rate = sample_rate
        self.modulator = VVVFModulator(sample_rate)
        self.acoustics = MotorAcousticModel(profile, sample_rate)
        self.motor_config = MotorEmulatorConfig.from_mapping(
            profile.motor_acoustics, sample_rate
        )
        self.motor_emulator = MotorAcousticEmulator(self.motor_config, sample_rate)
        self.motor_emulator.set_structural_resonances(profile.motor_acoustics)
        self._audio_model = AudioModel(self.motor_config.default_audio_model)
        self._previous_audio_model = self._audio_model
        self._crossfade_total_samples = max(
            int(round(self.motor_config.model_crossfade_ms * sample_rate / 1000.0)),
            1,
        )
        self._crossfade_remaining_samples = 0
        loudness_config = LoudnessCompensationConfig.from_mapping(
            profile.motor_acoustics
        )
        self._loudness_compensators: dict[AudioModel, MonitorLoudnessCompensator] = {}
        for audio_model in AudioModel:
            calibration = self._calibrate_audio_model(
                profile, sample_rate, loudness_config, audio_model
            )
            self._loudness_compensators[audio_model] = MonitorLoudnessCompensator(
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

    @property
    def loudness_compensator(self) -> MonitorLoudnessCompensator:
        """Compatibility access to the currently selected model's compensator."""
        return self._loudness_compensators[self._audio_model]

    @property
    def audio_model(self) -> AudioModel:
        return self._audio_model

    @classmethod
    def _calibrate_audio_model(
        cls,
        profile: VVVFProfile,
        sample_rate: int,
        config: LoudnessCompensationConfig,
        audio_model: AudioModel,
    ) -> tuple[LoudnessCalibrationPoint, ...]:
        cache_key = (
            audio_model.value,
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
                legacy_acoustics = MotorAcousticModel(profile, sample_rate)
                motor_config = MotorEmulatorConfig.from_mapping(
                    profile.motor_acoustics, sample_rate
                )
                motor_emulator = MotorAcousticEmulator(motor_config, sample_rate)
                motor_emulator.set_structural_resonances(profile.motor_acoustics)
                warmup = modulator.generate(
                    warmup_samples,
                    control_frequency_hz=float(frequency),
                    mode=region.mode,
                    carrier_frequency_hz=region.carrier_frequency_hz,
                    pulse_count=region.pulse_count,
                    amplitude=amplitude,
                )
                if audio_model is AudioModel.LEGACY_SWITCHING:
                    legacy_acoustics.process(warmup.excitation)
                else:
                    motor_emulator.process(
                        warmup.phase_voltage_abc, warmup.excitation
                    )
                measured = modulator.generate(
                    measure_samples,
                    control_frequency_hz=float(frequency),
                    mode=region.mode,
                    carrier_frequency_hz=region.carrier_frequency_hz,
                    pulse_count=region.pulse_count,
                    amplitude=amplitude,
                )
                if audio_model is AudioModel.LEGACY_SWITCHING:
                    raw_audio = legacy_acoustics.process(measured.excitation)
                else:
                    raw_audio = motor_emulator.process(
                        measured.phase_voltage_abc, measured.excitation
                    ).acoustic_output
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
        for compensator in self._loudness_compensators.values():
            compensator.set_enabled(enabled)

    def set_audio_model(self, audio_model: AudioModel | str) -> None:
        selected = AudioModel(audio_model)
        if selected is self._audio_model:
            return
        self._previous_audio_model = self._audio_model
        self._audio_model = selected
        self._crossfade_remaining_samples = self._crossfade_total_samples

    def reset(self) -> None:
        self.modulator.reset()
        self.acoustics.reset()
        self.motor_emulator.reset()
        for compensator in self._loudness_compensators.values():
            compensator.reset()
        self._previous_audio_model = self._audio_model
        self._crossfade_remaining_samples = 0
        self._last_sample = 0.0

    def synthesize(
        self, snapshot: SimulationSnapshot, num_samples: int
    ) -> NDArray[np.float32]:
        if snapshot.mode == "COAST" or snapshot.amplitude <= 0.0:
            legacy_excitation = np.zeros(num_samples, dtype=np.float64)
            phase_voltage_abc = np.zeros((3, num_samples), dtype=np.float64)
        else:
            block = self.modulator.generate(
                num_samples,
                control_frequency_hz=snapshot.control_frequency_hz,
                mode=ModulationMode(snapshot.mode),
                carrier_frequency_hz=snapshot.carrier_frequency_hz,
                pulse_count=snapshot.pulse_count,
                amplitude=snapshot.amplitude,
            )
            legacy_excitation = block.excitation
            phase_voltage_abc = block.phase_voltage_abc
        raw_by_model = {
            AudioModel.LEGACY_SWITCHING: self.acoustics.process(legacy_excitation),
            AudioModel.MOTOR_EMULATOR: self.motor_emulator.process(
                phase_voltage_abc, legacy_excitation
            ).acoustic_output,
        }
        compensated_by_model = {
            audio_model: self._loudness_compensators[audio_model].process(
                raw_audio,
                control_frequency_hz=snapshot.control_frequency_hz,
                mode=snapshot.mode,
                pulse_count=snapshot.pulse_count,
                profile_amplitude=snapshot.amplitude,
            )
            for audio_model, raw_audio in raw_by_model.items()
        }
        target = compensated_by_model[self._audio_model]
        if self._crossfade_remaining_samples > 0:
            start = (
                self._crossfade_total_samples - self._crossfade_remaining_samples
            )
            progress = np.clip(
                (start + np.arange(1, num_samples + 1, dtype=np.float64))
                / self._crossfade_total_samples,
                0.0,
                1.0,
            )
            previous = compensated_by_model[self._previous_audio_model]
            target = previous * (1.0 - progress) + target * progress
            self._crossfade_remaining_samples = max(
                self._crossfade_remaining_samples - num_samples, 0
            )
            if self._crossfade_remaining_samples == 0:
                self._previous_audio_model = self._audio_model
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

    def set_audio_model(self, audio_model: AudioModel | str) -> None:
        with self._lock:
            self.synthesizer.set_audio_model(audio_model)

    def reset_audio(self) -> None:
        with self._lock:
            self.synthesizer.reset()

    @property
    def audio_model(self) -> AudioModel:
        with self._lock:
            return self.synthesizer.audio_model

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
