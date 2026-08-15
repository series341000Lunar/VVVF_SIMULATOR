"""Replaceable vehicle-speed to motor-frequency models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LinearMotorFrequencyModel:
    """Stage A placeholder model: electrical Hz = km/h multiplied by a scale."""

    electrical_hz_per_kmh: float

    def electrical_frequency(self, speed_kmh: float) -> float:
        if speed_kmh < 0:
            raise ValueError("speed_kmh cannot be negative")
        return speed_kmh * self.electrical_hz_per_kmh
