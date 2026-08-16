"""Full-cycle artifact export and automatic validation."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import wavfile

from .model import AudioModel, DriveState, ModulationMode
from .offline_renderer import (
    AbortCallback,
    OfflineRenderConfig,
    OfflineRenderer,
    OfflineRenderResult,
    ProgressCallback,
    StateRecord,
    TransitionEvent,
)
from .profile import ModulationRegion, VVVFProfile
from .scenario import FullCycleScenario, ScenarioPhase
from .spectrogram import generate_spectrogram


STATE_COLUMNS = (
    "time_s",
    "scenario_phase",
    "master_command",
    "drive_state",
    "virtual_speed_kmh",
    "control_frequency_hz",
    "modulation_mode",
    "pulse_count",
    "carrier_frequency_hz",
    "profile_amplitude",
    "monitor_compensation_gain_db",
    "audio_model",
    "effective_switching_frequency_hz",
)
EVENT_COLUMNS = (
    "time_s",
    "scenario_phase",
    "event_type",
    "previous_value",
    "current_value",
)


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    start_frequency_hz: float
    maximum_frequency_hz: float
    final_frequency_hz: float
    powering_patterns_found: int
    powering_patterns_expected: int
    braking_patterns_found: int
    braking_patterns_expected: int
    powering_pass: bool
    coast_pass: bool
    braking_pass: bool
    audio_finite: bool
    audio_peak: float
    audio_peak_safe: bool
    audio_clipped_samples: int
    audio_clipping_free: bool
    audio_rms: float
    audio_non_silent: bool
    start_near_silence: bool
    end_near_silence: bool
    wav_duration_s: float
    csv_duration_s: float
    duration_mismatch_ms: float
    duration_pass: bool

    @property
    def all_passed(self) -> bool:
        return all(
            (
                self.powering_pass,
                self.coast_pass,
                self.braking_pass,
                self.audio_finite,
                self.audio_peak_safe,
                self.audio_clipping_free,
                self.audio_non_silent,
                self.start_near_silence,
                self.end_near_silence,
                self.duration_pass,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["all_passed"] = self.all_passed
        return result


@dataclass(frozen=True, slots=True)
class ExportedRun:
    run_directory: Path
    motor_wav: Path
    state_csv: Path
    events_csv: Path
    metadata_json: Path
    validation: ValidationSummary
    spectrogram_png: Path | None = None
    legacy_wav: Path | None = None


def _region_label(region: ModulationRegion) -> str:
    if region.mode is ModulationMode.ASYNC_PWM:
        return f"ASYNC {region.carrier_frequency_hz:g} Hz"
    return f"{region.pulse_count}P"


def _compressed_patterns(
    records: tuple[StateRecord, ...], drive_state: DriveState
) -> tuple[str, ...]:
    result: list[str] = []
    for record in records:
        if record.drive_state != drive_state.value:
            continue
        label = (
            f"ASYNC {record.carrier_frequency_hz:g} Hz"
            if record.modulation_mode == ModulationMode.ASYNC_PWM.value
            else f"{record.pulse_count}P"
        )
        if not result or result[-1] != label:
            result.append(label)
    return tuple(result)


def _rms(values: np.ndarray) -> float:
    if not len(values):
        return 0.0
    return float(np.sqrt(np.mean(np.square(values.astype(np.float64)))))


def validate_render(
    result: OfflineRenderResult, profile: VVVFProfile
) -> ValidationSummary:
    if not result.state_records:
        raise ValueError("Offline render contains no state records")
    records = result.state_records
    frequencies = np.asarray(
        [record.control_frequency_hz for record in records], dtype=np.float64
    )
    power_expected = tuple(
        _region_label(region) for region in profile.patterns[DriveState.POWERING].regions
    )
    brake_expected = tuple(
        _region_label(region)
        for region in reversed(profile.patterns[DriveState.BRAKING].regions)
    )
    power_observed = _compressed_patterns(records, DriveState.POWERING)
    brake_observed = _compressed_patterns(records, DriveState.BRAKING)
    coast_records = tuple(
        record
        for record in records
        if record.scenario_phase == ScenarioPhase.COAST.value
    )
    tolerance_hz = max(
        profile.drive_dynamics.power_frequency_rate_hz_per_s / 50.0
        if profile.drive_dynamics is not None
        else 0.1,
        0.1,
    )
    coast_pass = bool(coast_records) and all(
        abs(record.control_frequency_hz - profile.maximum_control_frequency_hz)
        <= tolerance_hz
        and record.pulse_count == profile.coast.pulse_count
        for record in coast_records
    )
    if coast_records:
        coast_pass = (
            coast_pass
            and coast_records[-1].profile_amplitude
            < coast_records[0].profile_amplitude
            and coast_records[-1].profile_amplitude < 0.02
        )
    audio64 = result.audio.astype(np.float64)
    audio_finite = bool(np.isfinite(audio64).all())
    peak = float(np.max(np.abs(audio64))) if len(audio64) else 0.0
    clipped_samples = int(np.count_nonzero(np.abs(audio64) >= 0.949999))
    audio_rms = _rms(audio64)
    silence_samples = min(int(round(0.1 * result.sample_rate)), len(audio64))
    start_rms = _rms(audio64[:silence_samples])
    end_rms = _rms(audio64[-silence_samples:])
    csv_duration = records[-1].time_s
    duration_mismatch_ms = abs(result.duration_seconds - csv_duration) * 1000.0
    duration_tolerance = 2.0 * result.block_size / result.sample_rate
    start_frequency = records[0].control_frequency_hz
    final_frequency = records[-1].control_frequency_hz
    maximum_frequency = float(np.max(frequencies))
    return ValidationSummary(
        start_frequency_hz=start_frequency,
        maximum_frequency_hz=maximum_frequency,
        final_frequency_hz=final_frequency,
        powering_patterns_found=len(set(power_observed).intersection(power_expected)),
        powering_patterns_expected=len(power_expected),
        braking_patterns_found=len(set(brake_observed).intersection(brake_expected)),
        braking_patterns_expected=len(brake_expected),
        powering_pass=(
            result.complete
            and abs(start_frequency - profile.minimum_control_frequency_hz) <= tolerance_hz
            and abs(maximum_frequency - profile.maximum_control_frequency_hz) <= tolerance_hz
            and all(label in power_observed for label in power_expected)
        ),
        coast_pass=coast_pass,
        braking_pass=(
            result.complete
            and abs(final_frequency - profile.minimum_control_frequency_hz) <= tolerance_hz
            and all(label in brake_observed for label in brake_expected)
        ),
        audio_finite=audio_finite,
        audio_peak=peak,
        audio_peak_safe=peak <= 0.950001,
        audio_clipped_samples=clipped_samples,
        audio_clipping_free=clipped_samples == 0,
        audio_rms=audio_rms,
        audio_non_silent=audio_rms > 1e-6,
        start_near_silence=start_rms < 0.01,
        end_near_silence=end_rms < 1e-4,
        wav_duration_s=result.duration_seconds,
        csv_duration_s=csv_duration,
        duration_mismatch_ms=duration_mismatch_ms,
        duration_pass=(
            abs(result.duration_seconds - result.scenario.total_duration_s)
            <= duration_tolerance
            and duration_mismatch_ms <= duration_tolerance * 1000.0
        ),
    )


def _format_csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.9f}"
    return value


def _write_state_csv(path: Path, records: tuple[StateRecord, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=STATE_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    key: _format_csv_value(value)
                    for key, value in asdict(record).items()
                }
            )


def _write_events_csv(path: Path, events: tuple[TransitionEvent, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=EVENT_COLUMNS)
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    key: _format_csv_value(value)
                    for key, value in asdict(event).items()
                }
            )


def _git_metadata(repository_root: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return commit, bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        return None, None


def _profile_reference(profile_path: Path, repository_root: Path) -> str:
    try:
        return str(profile_path.resolve().relative_to(repository_root.resolve()))
    except ValueError:
        return str(profile_path.resolve())


def _unique_run_paths(output_root: Path, timestamp: datetime) -> tuple[Path, Path]:
    base_name = timestamp.strftime("%Y%m%d_%H%M%S_mck01c_full_cycle")
    final = output_root / base_name
    suffix = 1
    while final.exists() or (output_root / f".partial_{final.name}").exists():
        final = output_root / f"{base_name}_{suffix:02d}"
        suffix += 1
    return final, output_root / f".partial_{final.name}"


def _write_wav(path: Path, result: OfflineRenderResult) -> None:
    pcm = np.round(np.clip(result.audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    wavfile.write(path, result.sample_rate, pcm)


def export_full_cycle(
    profile: VVVFProfile,
    *,
    output_root: Path,
    config: OfflineRenderConfig | None = None,
    include_legacy: bool = False,
    progress: ProgressCallback | None = None,
    abort_requested: AbortCallback | None = None,
) -> ExportedRun:
    selected_config = OfflineRenderConfig() if config is None else config
    if selected_config.audio_model is not AudioModel.MOTOR_EMULATOR:
        raise ValueError("Canonical full-cycle export must use MOTOR EMULATOR")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone()
    final_directory, partial_directory = _unique_run_paths(output_root, timestamp)
    partial_directory.mkdir()
    try:
        scenario = FullCycleScenario.from_profile(profile)
        result = OfflineRenderer(profile, selected_config).render(
            scenario,
            progress=progress,
            abort_requested=abort_requested,
        )
        validation = validate_render(result, profile)
        motor_wav = partial_directory / "motor.wav"
        state_csv = partial_directory / "state.csv"
        events_csv = partial_directory / "events.csv"
        spectrogram_png = partial_directory / "spectrogram.png"
        metadata_json = partial_directory / "run_metadata.json"
        _write_wav(motor_wav, result)
        _write_state_csv(state_csv, result.state_records)
        _write_events_csv(events_csv, result.events)
        generate_spectrogram(
            motor_wav,
            spectrogram_png,
            result.state_records,
            result.events,
        )
        repository_root = Path(__file__).parents[1]
        git_commit, git_dirty = _git_metadata(repository_root)
        profile_bytes = profile.source_path.read_bytes()
        metadata = {
            "timestamp": timestamp.isoformat(),
            "scenario_name": scenario.name,
            "status": "complete",
            "profile_name": profile.name,
            "profile_schema_version": profile.schema_version,
            "profile_verified": profile.verified,
            "profile_evidence_level": profile.evidence_level,
            "profile_file": _profile_reference(profile.source_path, repository_root),
            "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
            "sample_rate": result.sample_rate,
            "audio_block_size": result.block_size,
            "wav_format": "mono 16-bit PCM",
            "spectrogram_max_frequency_hz": 6_000.0,
            "csv_rate_hz": selected_config.csv_rate_hz,
            "audio_model": selected_config.audio_model.value,
            "loudness_compensation_enabled": selected_config.loudness_compensation_enabled,
            "master_volume": selected_config.master_volume,
            "power_rate_hz_per_s": scenario.power_rate_hz_per_s,
            "brake_rate_hz_per_s": scenario.brake_rate_hz_per_s,
            "coast_duration_s": scenario.coast_duration_s,
            "max_control_frequency_hz": scenario.maximum_control_frequency_hz,
            "motor_force_mix": profile.motor_acoustics.get("motor_force_mix"),
            "switching_leakage_mix": profile.motor_acoustics.get("switching_leakage_mix"),
            "motor_acoustic_parameters": profile.motor_acoustics,
            "render_duration_s": result.duration_seconds,
            "application_version": "VVVF Simulator Phase 1 Stage C",
            "git_commit": git_commit,
            "git_dirty": git_dirty,
            "validation": validation.to_dict(),
        }
        metadata_json.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        legacy_wav: Path | None = None
        if include_legacy:
            legacy_config = OfflineRenderConfig(
                sample_rate=selected_config.sample_rate,
                block_size=selected_config.block_size,
                csv_rate_hz=selected_config.csv_rate_hz,
                audio_model=AudioModel.LEGACY_SWITCHING,
                loudness_compensation_enabled=selected_config.loudness_compensation_enabled,
                master_volume=selected_config.master_volume,
            )
            legacy_result = OfflineRenderer(profile, legacy_config).render(
                scenario,
                progress=progress,
                abort_requested=abort_requested,
            )
            legacy_wav = partial_directory / "legacy.wav"
            _write_wav(legacy_wav, legacy_result)
        partial_directory.replace(final_directory)
        return ExportedRun(
            run_directory=final_directory,
            motor_wav=final_directory / motor_wav.name,
            state_csv=final_directory / state_csv.name,
            events_csv=final_directory / events_csv.name,
            metadata_json=final_directory / metadata_json.name,
            validation=validation,
            spectrogram_png=final_directory / spectrogram_png.name,
            legacy_wav=(
                None if legacy_wav is None else final_directory / legacy_wav.name
            ),
        )
    except BaseException:
        if partial_directory.exists():
            shutil.rmtree(partial_directory)
        raise
