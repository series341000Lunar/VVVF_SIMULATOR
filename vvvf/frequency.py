"""Input-layer mapping into the VVVF control-frequency domain."""

from __future__ import annotations

import math
from dataclasses import dataclass


def clamp_finite(value: float, minimum: float, maximum: float, name: str) -> float:
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return min(max(converted, minimum), maximum)


@dataclass(frozen=True, slots=True)
class LinearFrequencyMapper:
    """Configurable linear virtual-speed to control-frequency mapper."""

    vehicle_speed_min_kmh: float
    vehicle_speed_max_kmh: float
    control_frequency_min_hz: float
    control_frequency_max_hz: float
    data_notice: str

    def __post_init__(self) -> None:
        values = (
            self.vehicle_speed_min_kmh,
            self.vehicle_speed_max_kmh,
            self.control_frequency_min_hz,
            self.control_frequency_max_hz,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Frequency mapper bounds must be finite")
        if self.vehicle_speed_max_kmh <= self.vehicle_speed_min_kmh:
            raise ValueError("vehicle speed mapping range must be increasing")
        if self.control_frequency_max_hz <= self.control_frequency_min_hz:
            raise ValueError("control frequency mapping range must be increasing")

    def map_speed(self, vehicle_speed_kmh: float) -> float:
        speed = clamp_finite(
            vehicle_speed_kmh,
            self.vehicle_speed_min_kmh,
            self.vehicle_speed_max_kmh,
            "vehicle_speed_kmh",
        )
        ratio = (speed - self.vehicle_speed_min_kmh) / (
            self.vehicle_speed_max_kmh - self.vehicle_speed_min_kmh
        )
        return self.control_frequency_min_hz + ratio * (
            self.control_frequency_max_hz - self.control_frequency_min_hz
        )

    def unmap_control_frequency(self, control_frequency_hz: float) -> float:
        """Map a bounded control frequency back to virtual vehicle speed."""
        frequency = clamp_finite(
            control_frequency_hz,
            self.control_frequency_min_hz,
            self.control_frequency_max_hz,
            "control_frequency_hz",
        )
        ratio = (frequency - self.control_frequency_min_hz) / (
            self.control_frequency_max_hz - self.control_frequency_min_hz
        )
        return self.vehicle_speed_min_kmh + ratio * (
            self.vehicle_speed_max_kmh - self.vehicle_speed_min_kmh
        )
