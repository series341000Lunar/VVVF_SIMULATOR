"""Load and validate external VVVF research profiles."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_MODES = frozenset({"ASYNC_PWM", "SYNC_PULSE", "ONE_PULSE"})


class ProfileError(ValueError):
    """Raised when profile data is missing or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ModulationRegion:
    speed_start: float
    speed_end: float
    mode: str
    carrier_hz: float | None = None
    pulse_count: int | None = None


@dataclass(frozen=True, slots=True)
class VVVFProfile:
    name: str
    verified: bool
    description: str
    data_notice: str
    electrical_hz_per_kmh: float
    maximum_modulation_index: float
    powering: tuple[ModulationRegion, ...]
    source_path: Path

    @property
    def minimum_speed(self) -> float:
        return self.powering[0].speed_start

    @property
    def maximum_speed(self) -> float:
        return self.powering[-1].speed_end

    def region_for_speed(self, speed_kmh: float) -> ModulationRegion:
        """Return the half-open speed region, with the final end point included."""
        if not math.isfinite(speed_kmh):
            raise ProfileError("Speed must be a finite number")
        if speed_kmh < self.minimum_speed or speed_kmh > self.maximum_speed:
            raise ProfileError(
                f"Speed {speed_kmh:g} km/h is outside profile range "
                f"{self.minimum_speed:g}..{self.maximum_speed:g} km/h"
            )

        for index, region in enumerate(self.powering):
            is_final = index == len(self.powering) - 1
            if region.speed_start <= speed_kmh < region.speed_end:
                return region
            if is_final and speed_kmh == region.speed_end:
                return region

        raise ProfileError(f"No modulation region covers {speed_kmh:g} km/h")


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


def _parse_region(raw: Any, index: int) -> ModulationRegion:
    context = f"powering[{index}]"
    if not isinstance(raw, dict):
        raise ProfileError(f"{context} must be an object")

    start = _finite_number(_required(raw, "speed_start", context), f"{context}.speed_start")
    end = _finite_number(_required(raw, "speed_end", context), f"{context}.speed_end")
    mode = _required(raw, "mode", context)
    if not isinstance(mode, str) or mode not in SUPPORTED_MODES:
        raise ProfileError(
            f"{context}.mode must be one of {', '.join(sorted(SUPPORTED_MODES))}"
        )
    if start < 0 or end <= start:
        raise ProfileError(f"{context} must have 0 <= speed_start < speed_end")

    carrier_hz: float | None = None
    pulse_count: int | None = None
    if mode == "ASYNC_PWM":
        carrier_hz = _finite_number(
            _required(raw, "carrier_hz", context), f"{context}.carrier_hz"
        )
        if carrier_hz <= 0:
            raise ProfileError(f"{context}.carrier_hz must be positive")
    else:
        pulse_raw = _required(raw, "pulse_count", context)
        if isinstance(pulse_raw, bool) or not isinstance(pulse_raw, int) or pulse_raw <= 0:
            raise ProfileError(f"{context}.pulse_count must be a positive integer")
        pulse_count = pulse_raw
        if mode == "ONE_PULSE" and pulse_count != 1:
            raise ProfileError(f"{context}.pulse_count must be 1 for ONE_PULSE")

    return ModulationRegion(start, end, mode, carrier_hz, pulse_count)


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

    name = _required(raw, "name", "profile")
    description = _required(raw, "description", "profile")
    data_notice = _required(raw, "data_notice", "profile")
    verified = _required(raw, "verified", "profile")
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("profile.name must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ProfileError("profile.description must be a non-empty string")
    if not isinstance(data_notice, str) or not data_notice.strip():
        raise ProfileError("profile.data_notice must be a non-empty string")
    if not isinstance(verified, bool):
        raise ProfileError("profile.verified must be true or false")

    motor = _required(raw, "motor_frequency_model", "profile")
    if not isinstance(motor, dict):
        raise ProfileError("profile.motor_frequency_model must be an object")
    if motor.get("type") != "linear_scale":
        raise ProfileError("Only motor_frequency_model.type='linear_scale' is supported in Stage A")
    scale = _finite_number(
        _required(motor, "electrical_hz_per_kmh", "motor_frequency_model"),
        "motor_frequency_model.electrical_hz_per_kmh",
    )
    if scale <= 0:
        raise ProfileError("motor_frequency_model.electrical_hz_per_kmh must be positive")

    max_index = _finite_number(
        raw.get("maximum_modulation_index", 0.95), "maximum_modulation_index"
    )
    if not 0 < max_index <= 1:
        raise ProfileError("maximum_modulation_index must be in the range (0, 1]")

    powering_raw = _required(raw, "powering", "profile")
    if not isinstance(powering_raw, list) or not powering_raw:
        raise ProfileError("profile.powering must be a non-empty array")
    powering = tuple(_parse_region(item, index) for index, item in enumerate(powering_raw))
    if powering[0].speed_start != 0:
        raise ProfileError("The first powering region must start at 0 km/h")
    for previous, current in zip(powering, powering[1:]):
        if previous.speed_end != current.speed_start:
            raise ProfileError(
                "Powering regions must be ordered and contiguous: "
                f"{previous.speed_end:g} != {current.speed_start:g}"
            )

    return VVVFProfile(
        name=name.strip(),
        verified=verified,
        description=description.strip(),
        data_notice=data_notice.strip(),
        electrical_hz_per_kmh=scale,
        maximum_modulation_index=max_index,
        powering=powering,
        source_path=source_path,
    )
