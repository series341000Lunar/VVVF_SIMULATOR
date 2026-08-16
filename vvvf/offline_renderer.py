"""Deterministic full-cycle audio rendering without an audio device."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .audio import AudioSynthesizer
from .model import AudioModel
from .profile import VVVFProfile
from .scenario import FullCycleScenario, ScenarioPhase, ScenarioRunner
from .state import SimulationSnapshot


Float32Array = NDArray[np.float32]


class RenderAborted(RuntimeError):
    """Raised when a caller requests cooperative offline-render cancellation."""


@dataclass(frozen=True, slots=True)
class OfflineRenderConfig:
    sample_rate: int = 48_000
    block_size: int = 480
    csv_rate_hz: int = 50
    audio_model: AudioModel = AudioModel.MOTOR_EMULATOR
    loudness_compensation_enabled: bool = True
    master_volume: float = 0.8

    def __post_init__(self) -> None:
        if self.sample_rate < 8_000:
            raise ValueError("sample_rate must be at least 8000 Hz")
        if self.block_size <= 0 or self.sample_rate % self.block_size:
            raise ValueError("block_size must divide sample_rate exactly")
        if self.csv_rate_hz <= 0 or self.sample_rate % self.csv_rate_hz:
            raise ValueError("csv_rate_hz must divide sample_rate exactly")
        if not math.isfinite(self.master_volume) or not 0 <= self.master_volume <= 1:
            raise ValueError("master_volume must be finite and within [0, 1]")


@dataclass(frozen=True, slots=True)
class StateRecord:
    time_s: float
    scenario_phase: str
    master_command: float
    drive_state: str
    virtual_speed_kmh: float
    control_frequency_hz: float
    modulation_mode: str
    pulse_count: int | None
    carrier_frequency_hz: float | None
    profile_amplitude: float
    monitor_compensation_gain_db: float
    audio_model: str
    effective_switching_frequency_hz: float


@dataclass(frozen=True, slots=True)
class TransitionEvent:
    time_s: float
    scenario_phase: str
    event_type: str
    previous_value: str
    current_value: str


@dataclass(frozen=True, slots=True)
class OfflineRenderResult:
    audio: Float32Array
    state_records: tuple[StateRecord, ...]
    events: tuple[TransitionEvent, ...]
    sample_rate: int
    block_size: int
    scenario: FullCycleScenario
    complete: bool

    @property
    def duration_seconds(self) -> float:
        return len(self.audio) / self.sample_rate


ProgressCallback = Callable[[float, str], None]
AbortCallback = Callable[[], bool]


def _pattern_label(snapshot: SimulationSnapshot) -> str:
    if snapshot.mode == "ASYNC_PWM":
        carrier = 0.0 if snapshot.carrier_frequency_hz is None else snapshot.carrier_frequency_hz
        return f"ASYNC {carrier:g} Hz"
    if snapshot.pulse_count is not None:
        return f"{snapshot.pulse_count}P"
    return snapshot.mode


def _effective_switching_frequency(snapshot: SimulationSnapshot) -> float:
    if snapshot.carrier_frequency_hz is not None:
        return snapshot.carrier_frequency_hz
    if snapshot.pulse_count is not None:
        return snapshot.control_frequency_hz * snapshot.pulse_count
    return 0.0


class OfflineRenderer:
    """Render the same AudioSynthesizer DSP used by realtime playback."""

    def __init__(
        self, profile: VVVFProfile, config: OfflineRenderConfig | None = None
    ) -> None:
        self.profile = profile
        self.config = OfflineRenderConfig() if config is None else config

    def _record(
        self,
        time_s: float,
        phase: ScenarioPhase,
        snapshot: SimulationSnapshot,
        synthesizer: AudioSynthesizer,
    ) -> StateRecord:
        return StateRecord(
            time_s=time_s,
            scenario_phase=phase.value,
            master_command=snapshot.master_command,
            drive_state=snapshot.drive_state,
            virtual_speed_kmh=snapshot.vehicle_speed_kmh,
            control_frequency_hz=snapshot.control_frequency_hz,
            modulation_mode=snapshot.mode,
            pulse_count=snapshot.pulse_count,
            carrier_frequency_hz=snapshot.carrier_frequency_hz,
            profile_amplitude=snapshot.amplitude,
            monitor_compensation_gain_db=synthesizer.monitor_gain_db,
            audio_model=synthesizer.audio_model.value,
            effective_switching_frequency_hz=_effective_switching_frequency(snapshot),
        )

    def render(
        self,
        scenario: FullCycleScenario | None = None,
        *,
        progress: ProgressCallback | None = None,
        abort_requested: AbortCallback | None = None,
        duration_limit_s: float | None = None,
    ) -> OfflineRenderResult:
        selected_scenario = (
            FullCycleScenario.from_profile(self.profile)
            if scenario is None
            else scenario
        )
        if duration_limit_s is not None and (
            not math.isfinite(duration_limit_s) or duration_limit_s <= 0
        ):
            raise ValueError("duration_limit_s must be positive and finite")
        runner = ScenarioRunner(self.profile, selected_scenario)
        synthesizer = AudioSynthesizer(
            self.profile,
            sample_rate=self.config.sample_rate,
            master_volume=self.config.master_volume,
        )
        synthesizer.set_audio_model(self.config.audio_model)
        synthesizer.set_loudness_compensation(
            self.config.loudness_compensation_enabled
        )
        log_interval_samples = self.config.sample_rate // self.config.csv_rate_hz
        maximum_samples = int(round(selected_scenario.total_duration_s * self.config.sample_rate))
        if duration_limit_s is not None:
            maximum_samples = min(
                maximum_samples,
                int(round(duration_limit_s * self.config.sample_rate)),
            )
        rendered_samples = 0
        next_log_sample = 0
        audio_blocks: list[Float32Array] = []
        records: list[StateRecord] = []
        events: list[TransitionEvent] = [
            TransitionEvent(0.0, runner.phase.value, "SCENARIO_PHASE", "", runner.phase.value),
            TransitionEvent(0.0, runner.phase.value, "MODULATION", "", _pattern_label(runner.snapshot())),
        ]
        previous_phase = runner.phase
        previous_pattern = _pattern_label(runner.snapshot())

        while rendered_samples < maximum_samples and not runner.complete:
            if abort_requested is not None and abort_requested():
                raise RenderAborted("Offline render aborted")
            remaining_samples = maximum_samples - rendered_samples
            phase_samples = max(
                int(round(runner.seconds_until_transition * self.config.sample_rate)),
                1,
            )
            chunk_samples = min(
                self.config.block_size, remaining_samples, phase_samples
            )
            snapshot = runner.snapshot()
            phase = runner.phase
            audio_blocks.append(synthesizer.synthesize(snapshot, chunk_samples))
            while next_log_sample <= rendered_samples:
                records.append(
                    self._record(
                        next_log_sample / self.config.sample_rate,
                        phase,
                        snapshot,
                        synthesizer,
                    )
                )
                next_log_sample += log_interval_samples
            rendered_samples += chunk_samples
            runner.advance(chunk_samples / self.config.sample_rate)
            next_snapshot = runner.snapshot()
            next_pattern = _pattern_label(next_snapshot)
            if runner.phase is not previous_phase:
                events.append(
                    TransitionEvent(
                        rendered_samples / self.config.sample_rate,
                        runner.phase.value,
                        "SCENARIO_PHASE",
                        previous_phase.value,
                        runner.phase.value,
                    )
                )
                previous_phase = runner.phase
            if next_pattern != previous_pattern:
                events.append(
                    TransitionEvent(
                        rendered_samples / self.config.sample_rate,
                        runner.phase.value,
                        "MODULATION",
                        previous_pattern,
                        next_pattern,
                    )
                )
                previous_pattern = next_pattern
            if progress is not None:
                progress(
                    rendered_samples / max(maximum_samples, 1),
                    runner.phase.value,
                )

        final_snapshot = runner.snapshot()
        final_phase = runner.phase
        final_time = rendered_samples / self.config.sample_rate
        if not records or not math.isclose(records[-1].time_s, final_time):
            records.append(
                self._record(final_time, final_phase, final_snapshot, synthesizer)
            )
        if runner.complete:
            events.append(
                TransitionEvent(
                    final_time,
                    final_phase.value,
                    "SCENARIO_COMPLETE",
                    final_phase.value,
                    "COMPLETE",
                )
            )
        audio = (
            np.concatenate(audio_blocks).astype(np.float32, copy=False)
            if audio_blocks
            else np.empty(0, dtype=np.float32)
        )
        return OfflineRenderResult(
            audio=audio,
            state_records=tuple(records),
            events=tuple(events),
            sample_rate=self.config.sample_rate,
            block_size=self.config.block_size,
            scenario=selected_scenario,
            complete=runner.complete,
        )
