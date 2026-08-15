"""Load and normalize MK1/MK2 external VVVF research profiles."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frequency import LinearFrequencyMapper, clamp_finite
from .model import DriveState, InterpolationType, ModulationMode


SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})


class ProfileError(ValueError):
    """Raised when profile data is missing or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ModulationRegion:
    control_frequency_start_hz: float
    control_frequency_end_hz: float
    mode: ModulationMode
    carrier_frequency_hz: float | None = None
    pulse_count: int | None = None
    label: str = ""

    @property
    def carrier_hz(self) -> float | None:
        """MK1 compatibility alias."""
        return self.carrier_frequency_hz


@dataclass(frozen=True, slots=True)
class AmplitudeKeyframe:
    control_frequency_hz: float
    amplitude: float
    interpolation: InterpolationType = InterpolationType.LINEAR


@dataclass(frozen=True, slots=True)
class AmplitudeCurve:
    keyframes: tuple[AmplitudeKeyframe, ...]

    def evaluate(self, control_frequency_hz: float) -> float:
        if not math.isfinite(control_frequency_hz):
            raise ProfileError("control_frequency_hz must be finite")
        if control_frequency_hz <= self.keyframes[0].control_frequency_hz:
            return self.keyframes[0].amplitude
        if control_frequency_hz >= self.keyframes[-1].control_frequency_hz:
            return self.keyframes[-1].amplitude
        for left, right in zip(self.keyframes, self.keyframes[1:]):
            if control_frequency_hz == right.control_frequency_hz:
                return right.amplitude
            if left.control_frequency_hz <= control_frequency_hz < right.control_frequency_hz:
                if right.interpolation in {
                    InterpolationType.STEP,
                    InterpolationType.HOLD,
                }:
                    return left.amplitude
                ratio = (control_frequency_hz - left.control_frequency_hz) / (
                    right.control_frequency_hz - left.control_frequency_hz
                )
                return left.amplitude + ratio * (right.amplitude - left.amplitude)
        raise ProfileError("Amplitude curve has no matching segment")


@dataclass(frozen=True, slots=True)
class DrivePattern:
    regions: tuple[ModulationRegion, ...]
    amplitude: AmplitudeCurve


@dataclass(frozen=True, slots=True)
class CoastProfile:
    mode: ModulationMode | None
    pulse_count: int | None
    hold_control_frequency: bool
    decay_seconds: float
    decay_notice: str
    envelope: tuple[tuple[float, float], ...]

    def envelope_gain(self, elapsed_seconds: float) -> float:
        if self.decay_seconds <= 0:
            return 0.0
        progress = min(max(elapsed_seconds / self.decay_seconds, 0.0), 1.0)
        for left, right in zip(self.envelope, self.envelope[1:]):
            if progress <= right[0]:
                span = right[0] - left[0]
                if span == 0:
                    return right[1]
                ratio = (progress - left[0]) / span
                return left[1] + ratio * (right[1] - left[1])
        return self.envelope[-1][1]


@dataclass(frozen=True, slots=True)
class VVVFProfile:
    schema_version: int
    name: str
    verified: bool
    evidence_level: str
    description: str
    data_notice: str
    frequency_mapper: LinearFrequencyMapper
    minimum_control_frequency_hz: float
    maximum_control_frequency_hz: float
    transition_hysteresis_hz: float
    patterns: dict[DriveState, DrivePattern]
    coast: CoastProfile
    motor_acoustics: dict[str, Any]
    source_path: Path

    @property
    def powering(self) -> tuple[ModulationRegion, ...]:
        return self.patterns[DriveState.POWERING].regions

    @property
    def braking(self) -> tuple[ModulationRegion, ...]:
        pattern = self.patterns.get(DriveState.BRAKING)
        return () if pattern is None else pattern.regions

    @property
    def minimum_speed(self) -> float:
        return self.frequency_mapper.vehicle_speed_min_kmh

    @property
    def maximum_speed(self) -> float:
        return self.frequency_mapper.vehicle_speed_max_kmh

    @property
    def electrical_hz_per_kmh(self) -> float:
        """MK1 compatibility alias for the mapper slope."""
        return (
            self.frequency_mapper.control_frequency_max_hz
            - self.frequency_mapper.control_frequency_min_hz
        ) / (
            self.frequency_mapper.vehicle_speed_max_kmh
            - self.frequency_mapper.vehicle_speed_min_kmh
        )

    @property
    def maximum_modulation_index(self) -> float:
        """MK1 compatibility value derived from the powering curve."""
        return max(
            frame.amplitude
            for frame in self.patterns[DriveState.POWERING].amplitude.keyframes
        )

    def clamp_control_frequency(self, control_frequency_hz: float) -> float:
        try:
            return clamp_finite(
                control_frequency_hz,
                self.minimum_control_frequency_hz,
                self.maximum_control_frequency_hz,
                "control_frequency_hz",
            )
        except ValueError as exc:
            raise ProfileError(str(exc)) from exc

    def region_for_control_frequency(
        self,
        control_frequency_hz: float,
        drive_state: DriveState | str = DriveState.POWERING,
    ) -> ModulationRegion:
        state = DriveState(drive_state)
        if state is DriveState.COAST:
            raise ProfileError("COAST uses its dedicated coast profile")
        if state not in self.patterns:
            raise ProfileError(f"No profile pattern for {state.value}")
        frequency = self.clamp_control_frequency(control_frequency_hz)
        regions = self.patterns[state].regions
        for index, region in enumerate(regions):
            is_final = index == len(regions) - 1
            if region.control_frequency_start_hz <= frequency < region.control_frequency_end_hz:
                return region
            if is_final and frequency == region.control_frequency_end_hz:
                return region
        raise ProfileError(f"No {state.value} region covers {frequency:g} Hz")

    def amplitude_for_control_frequency(
        self,
        control_frequency_hz: float,
        drive_state: DriveState | str = DriveState.POWERING,
    ) -> float:
        state = DriveState(drive_state)
        if state not in self.patterns:
            raise ProfileError(f"No amplitude curve for {state.value}")
        frequency = self.clamp_control_frequency(control_frequency_hz)
        return self.patterns[state].amplitude.evaluate(frequency)

    def region_for_speed(self, speed_kmh: float) -> ModulationRegion:
        """MK1 route through the mapper, never through speed regions."""
        return self.region_for_control_frequency(
            self.frequency_mapper.map_speed(speed_kmh), DriveState.POWERING
        )


def _required(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ProfileError(f"Missing '{key}' in {context}")
    return mapping[key]


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{context} must be a number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ProfileError(f"{context} must be finite")
    return converted


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{context} must be a non-empty string")
    return value.strip()


def _parse_mode(
    value: Any, context: str, *, normalize_one_pulse: bool = True
) -> tuple[ModulationMode, bool]:
    text = _nonempty_string(value, context)
    if text == "ONE_PULSE":
        if normalize_one_pulse:
            return ModulationMode.SYNC_PULSE, True
        return ModulationMode.ONE_PULSE, True
    try:
        return ModulationMode(text), False
    except ValueError as exc:
        raise ProfileError(
            f"{context} must be one of ASYNC_PWM, SYNC_PULSE, ONE_PULSE"
        ) from exc


def _validate_regions(
    regions: tuple[ModulationRegion, ...], minimum: float, maximum: float, context: str
) -> None:
    if not regions:
        raise ProfileError(f"{context} must contain at least one region")
    if regions[0].control_frequency_start_hz != minimum:
        raise ProfileError(f"{context} must start at {minimum:g} Hz")
    if regions[-1].control_frequency_end_hz != maximum:
        raise ProfileError(f"{context} must end at {maximum:g} Hz")
    for previous, current in zip(regions, regions[1:]):
        if previous.control_frequency_end_hz != current.control_frequency_start_hz:
            raise ProfileError(
                f"{context} regions must be ordered and contiguous: "
                f"{previous.control_frequency_end_hz:g} != "
                f"{current.control_frequency_start_hz:g}"
            )


def _parse_v2_regions(
    raw_regions: Any, context: str, minimum: float, maximum: float
) -> tuple[ModulationRegion, ...]:
    if not isinstance(raw_regions, list):
        raise ProfileError(f"{context} must be an array")
    parsed: list[ModulationRegion] = []
    for index, raw in enumerate(raw_regions):
        item_context = f"{context}[{index}]"
        if not isinstance(raw, dict):
            raise ProfileError(f"{item_context} must be an object")
        start = _finite_number(
            _required(raw, "control_frequency_start_hz", item_context),
            f"{item_context}.control_frequency_start_hz",
        )
        end = _finite_number(
            _required(raw, "control_frequency_end_hz", item_context),
            f"{item_context}.control_frequency_end_hz",
        )
        if start < minimum or end <= start or end > maximum:
            raise ProfileError(f"{item_context} has invalid control-frequency bounds")
        mode, one_pulse_alias = _parse_mode(
            _required(raw, "mode", item_context), f"{item_context}.mode"
        )
        carrier: float | None = None
        pulse: int | None = None
        if mode is ModulationMode.ASYNC_PWM:
            carrier = _finite_number(
                _required(raw, "carrier_frequency_hz", item_context),
                f"{item_context}.carrier_frequency_hz",
            )
            if carrier <= 0:
                raise ProfileError(f"{item_context}.carrier_frequency_hz must be positive")
        else:
            pulse_raw = 1 if one_pulse_alias else _required(raw, "pulse_count", item_context)
            if isinstance(pulse_raw, bool) or not isinstance(pulse_raw, int) or pulse_raw <= 0:
                raise ProfileError(f"{item_context}.pulse_count must be a positive integer")
            pulse = pulse_raw
        parsed.append(
            ModulationRegion(
                start,
                end,
                mode,
                carrier,
                pulse,
                str(raw.get("label", "")),
            )
        )
    result = tuple(parsed)
    _validate_regions(result, minimum, maximum, context)
    return result


def _parse_amplitude_curve(
    raw: Any, context: str, minimum: float, maximum: float
) -> AmplitudeCurve:
    if not isinstance(raw, dict):
        raise ProfileError(f"{context} must be an object")
    raw_frames = _required(raw, "keyframes", context)
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ProfileError(f"{context}.keyframes must be a non-empty array")
    frames: list[AmplitudeKeyframe] = []
    for index, item in enumerate(raw_frames):
        item_context = f"{context}.keyframes[{index}]"
        if not isinstance(item, dict):
            raise ProfileError(f"{item_context} must be an object")
        frequency = _finite_number(
            _required(item, "control_frequency_hz", item_context),
            f"{item_context}.control_frequency_hz",
        )
        amplitude = _finite_number(
            _required(item, "amplitude", item_context), f"{item_context}.amplitude"
        )
        if not 0 <= amplitude <= 1:
            raise ProfileError(f"{item_context}.amplitude must be in [0, 1]")
        try:
            interpolation = InterpolationType(str(item.get("interpolation", "LINEAR")))
        except ValueError as exc:
            raise ProfileError(
                f"{item_context}.interpolation must be LINEAR, STEP, or HOLD"
            ) from exc
        frames.append(AmplitudeKeyframe(frequency, amplitude, interpolation))
    if frames[0].control_frequency_hz != minimum:
        raise ProfileError(f"{context} must start at {minimum:g} Hz")
    if frames[-1].control_frequency_hz != maximum:
        raise ProfileError(f"{context} must end at {maximum:g} Hz")
    for left, right in zip(frames, frames[1:]):
        if right.control_frequency_hz <= left.control_frequency_hz:
            raise ProfileError(f"{context} keyframe frequencies must be strictly increasing")
    return AmplitudeCurve(tuple(frames))


def _load_v1(raw: dict[str, Any], source_path: Path) -> VVVFProfile:
    """Normalize the MK1 speed-region schema without mutating source data."""
    name = _nonempty_string(_required(raw, "name", "profile"), "profile.name")
    description = _nonempty_string(
        _required(raw, "description", "profile"), "profile.description"
    )
    data_notice = _nonempty_string(
        _required(raw, "data_notice", "profile"), "profile.data_notice"
    )
    verified = _required(raw, "verified", "profile")
    if not isinstance(verified, bool):
        raise ProfileError("profile.verified must be true or false")
    motor = _required(raw, "motor_frequency_model", "profile")
    if not isinstance(motor, dict) or motor.get("type") != "linear_scale":
        raise ProfileError("MK1 motor_frequency_model must use type='linear_scale'")
    scale = _finite_number(
        _required(motor, "electrical_hz_per_kmh", "motor_frequency_model"),
        "motor_frequency_model.electrical_hz_per_kmh",
    )
    if scale <= 0:
        raise ProfileError("motor_frequency_model.electrical_hz_per_kmh must be positive")
    raw_regions = _required(raw, "powering", "profile")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise ProfileError("profile.powering must be a non-empty array")
    regions: list[ModulationRegion] = []
    previous_speed_end: float | None = None
    for index, item in enumerate(raw_regions):
        context = f"powering[{index}]"
        if not isinstance(item, dict):
            raise ProfileError(f"{context} must be an object")
        speed_start = _finite_number(
            _required(item, "speed_start", context), f"{context}.speed_start"
        )
        speed_end = _finite_number(
            _required(item, "speed_end", context), f"{context}.speed_end"
        )
        if speed_start < 0 or speed_end <= speed_start:
            raise ProfileError(f"{context} must have 0 <= speed_start < speed_end")
        if previous_speed_end is not None and previous_speed_end != speed_start:
            raise ProfileError(
                "Powering regions must be ordered and contiguous: "
                f"{previous_speed_end:g} != {speed_start:g}"
            )
        previous_speed_end = speed_end
        mode, one_pulse_alias = _parse_mode(
            _required(item, "mode", context),
            f"{context}.mode",
            normalize_one_pulse=False,
        )
        carrier: float | None = None
        pulse: int | None = None
        if mode is ModulationMode.ASYNC_PWM:
            carrier = _finite_number(
                _required(item, "carrier_hz", context), f"{context}.carrier_hz"
            )
            if carrier <= 0:
                raise ProfileError(f"{context}.carrier_hz must be positive")
        else:
            pulse_raw = 1 if one_pulse_alias else _required(item, "pulse_count", context)
            if isinstance(pulse_raw, bool) or not isinstance(pulse_raw, int) or pulse_raw <= 0:
                raise ProfileError(f"{context}.pulse_count must be a positive integer")
            pulse = pulse_raw
        regions.append(
            ModulationRegion(speed_start * scale, speed_end * scale, mode, carrier, pulse)
        )
    maximum_speed = float(previous_speed_end)
    maximum_control = maximum_speed * scale
    maximum_index = _finite_number(
        raw.get("maximum_modulation_index", 0.95), "maximum_modulation_index"
    )
    if not 0 < maximum_index <= 1:
        raise ProfileError("maximum_modulation_index must be in (0, 1]")
    mapper = LinearFrequencyMapper(
        0.0,
        maximum_speed,
        0.0,
        maximum_control,
        "LEGACY MK1 LINEAR MAPPING — NOT VERIFIED VEHICLE DATA",
    )
    amplitude = AmplitudeCurve(
        (
            AmplitudeKeyframe(0.0, maximum_index),
            AmplitudeKeyframe(maximum_control, maximum_index),
        )
    )
    return VVVFProfile(
        schema_version=1,
        name=name,
        verified=verified,
        evidence_level="legacy_placeholder",
        description=description,
        data_notice=data_notice,
        frequency_mapper=mapper,
        minimum_control_frequency_hz=0.0,
        maximum_control_frequency_hz=maximum_control,
        transition_hysteresis_hz=0.0,
        patterns={DriveState.POWERING: DrivePattern(tuple(regions), amplitude)},
        coast=CoastProfile(
            None,
            None,
            True,
            0.0,
            "LEGACY MK1 COAST",
            ((0.0, 0.0), (1.0, 0.0)),
        ),
        motor_acoustics=dict(raw.get("motor_acoustics", {})),
        source_path=source_path,
    )


def _load_v2(raw: dict[str, Any], source_path: Path) -> VVVFProfile:
    metadata = _required(raw, "metadata", "profile")
    if not isinstance(metadata, dict):
        raise ProfileError("profile.metadata must be an object")
    name = _nonempty_string(_required(metadata, "name", "metadata"), "metadata.name")
    verified = _required(metadata, "verified", "metadata")
    if not isinstance(verified, bool):
        raise ProfileError("metadata.verified must be true or false")
    evidence_level = _nonempty_string(
        _required(metadata, "evidence_level", "metadata"), "metadata.evidence_level"
    )
    description = _nonempty_string(
        _required(metadata, "description", "metadata"), "metadata.description"
    )
    data_notice = _nonempty_string(
        _required(metadata, "data_notice", "metadata"), "metadata.data_notice"
    )
    mapping = _required(raw, "input_mapping", "profile")
    if not isinstance(mapping, dict) or mapping.get("type") != "linear":
        raise ProfileError("input_mapping must use type='linear'")
    mapper = LinearFrequencyMapper(
        _finite_number(_required(mapping, "vehicle_speed_min_kmh", "input_mapping"), "input_mapping.vehicle_speed_min_kmh"),
        _finite_number(_required(mapping, "vehicle_speed_max_kmh", "input_mapping"), "input_mapping.vehicle_speed_max_kmh"),
        _finite_number(_required(mapping, "control_frequency_min_hz", "input_mapping"), "input_mapping.control_frequency_min_hz"),
        _finite_number(_required(mapping, "control_frequency_max_hz", "input_mapping"), "input_mapping.control_frequency_max_hz"),
        _nonempty_string(_required(mapping, "data_notice", "input_mapping"), "input_mapping.data_notice"),
    )
    limits = _required(raw, "limits", "profile")
    if not isinstance(limits, dict):
        raise ProfileError("profile.limits must be an object")
    minimum = _finite_number(
        limits.get("min_control_frequency_hz", 0.0), "limits.min_control_frequency_hz"
    )
    maximum = _finite_number(
        _required(limits, "max_control_frequency_hz", "limits"),
        "limits.max_control_frequency_hz",
    )
    if minimum < 0 or maximum <= minimum:
        raise ProfileError("Control-frequency limits must be increasing and non-negative")
    hysteresis = _finite_number(
        raw.get("transition_hysteresis_hz", 0.0), "transition_hysteresis_hz"
    )
    if hysteresis < 0:
        raise ProfileError("transition_hysteresis_hz cannot be negative")
    patterns: dict[DriveState, DrivePattern] = {}
    for state, key in (
        (DriveState.POWERING, "powering"),
        (DriveState.BRAKING, "braking"),
    ):
        pattern_raw = _required(raw, key, "profile")
        if not isinstance(pattern_raw, dict):
            raise ProfileError(f"profile.{key} must be an object")
        regions = _parse_v2_regions(
            _required(pattern_raw, "regions", key), f"{key}.regions", minimum, maximum
        )
        amplitude = _parse_amplitude_curve(
            _required(pattern_raw, "amplitude", key),
            f"{key}.amplitude",
            minimum,
            maximum,
        )
        patterns[state] = DrivePattern(regions, amplitude)
    coast_raw = _required(raw, "coast", "profile")
    if not isinstance(coast_raw, dict):
        raise ProfileError("profile.coast must be an object")
    coast_mode, coast_one_pulse = _parse_mode(
        _required(coast_raw, "mode", "coast"), "coast.mode"
    )
    coast_pulse_raw = 1 if coast_one_pulse else coast_raw.get("pulse_count")
    if (
        coast_mode is not ModulationMode.SYNC_PULSE
        or isinstance(coast_pulse_raw, bool)
        or not isinstance(coast_pulse_raw, int)
        or coast_pulse_raw <= 0
    ):
        raise ProfileError("coast must use SYNC_PULSE with a positive pulse_count")
    decay_seconds = _finite_number(
        _required(coast_raw, "decay_seconds", "coast"), "coast.decay_seconds"
    )
    if decay_seconds <= 0:
        raise ProfileError("coast.decay_seconds must be positive")
    envelope_raw = _required(coast_raw, "amplitude_envelope", "coast")
    if not isinstance(envelope_raw, list) or len(envelope_raw) < 2:
        raise ProfileError("coast.amplitude_envelope must contain at least two points")
    envelope: list[tuple[float, float]] = []
    for index, point in enumerate(envelope_raw):
        context = f"coast.amplitude_envelope[{index}]"
        if not isinstance(point, dict):
            raise ProfileError(f"{context} must be an object")
        progress = _finite_number(
            _required(point, "progress", context), f"{context}.progress"
        )
        amplitude = _finite_number(
            _required(point, "amplitude", context), f"{context}.amplitude"
        )
        if not 0 <= progress <= 1 or not 0 <= amplitude <= 1:
            raise ProfileError(f"{context} values must be in [0, 1]")
        envelope.append((progress, amplitude))
    if envelope[0][0] != 0 or envelope[-1][0] != 1:
        raise ProfileError("coast amplitude envelope must span progress 0..1")
    if any(right[0] <= left[0] for left, right in zip(envelope, envelope[1:])):
        raise ProfileError("coast amplitude envelope progress must be increasing")
    hold_control_frequency = _required(coast_raw, "hold_control_frequency", "coast")
    if not isinstance(hold_control_frequency, bool):
        raise ProfileError("coast.hold_control_frequency must be true or false")
    coast = CoastProfile(
        coast_mode,
        coast_pulse_raw,
        hold_control_frequency,
        decay_seconds,
        _nonempty_string(
            _required(coast_raw, "decay_notice", "coast"), "coast.decay_notice"
        ),
        tuple(envelope),
    )
    return VVVFProfile(
        schema_version=2,
        name=name,
        verified=verified,
        evidence_level=evidence_level,
        description=description,
        data_notice=data_notice,
        frequency_mapper=mapper,
        minimum_control_frequency_hz=minimum,
        maximum_control_frequency_hz=maximum,
        transition_hysteresis_hz=hysteresis,
        patterns=patterns,
        coast=coast,
        motor_acoustics=dict(raw.get("motor_acoustics", {})),
        source_path=source_path,
    )


def load_profile(path: str | Path) -> VVVFProfile:
    source_path = Path(path).expanduser().resolve()
    try:
        with source_path.open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
    except json.JSONDecodeError as exc:
        raise ProfileError(
            f"Invalid JSON in {source_path}: line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not isinstance(raw, dict):
        raise ProfileError("Profile root must be an object")
    version_raw = raw.get("schema_version", 1)
    if isinstance(version_raw, bool) or not isinstance(version_raw, int):
        raise ProfileError("schema_version must be an integer")
    if version_raw not in SUPPORTED_SCHEMA_VERSIONS:
        raise ProfileError(
            f"Unsupported profile schema_version {version_raw}; supported versions are 1 and 2"
        )
    return _load_v1(raw, source_path) if version_raw == 1 else _load_v2(raw, source_path)
