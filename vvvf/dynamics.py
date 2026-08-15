"""Time-based control-frequency dynamics for MK3 drive simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .frequency import clamp_finite
from .model import DriveState


@dataclass(frozen=True, slots=True)
class DriveDynamicsConfig:
    """Profile-owned tuning for the virtual master controller."""

    power_frequency_rate_hz_per_s: float
    brake_frequency_rate_hz_per_s: float
    controller_dead_zone: float
    controller_maximum_command: float
    data_notice: str

    def __post_init__(self) -> None:
        numeric_values = (
            self.power_frequency_rate_hz_per_s,
            self.brake_frequency_rate_hz_per_s,
            self.controller_dead_zone,
            self.controller_maximum_command,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError("Drive dynamics values must be finite")
        if self.power_frequency_rate_hz_per_s <= 0:
            raise ValueError("Power frequency rate must be positive")
        if self.brake_frequency_rate_hz_per_s <= 0:
            raise ValueError("Brake frequency rate must be positive")
        if self.controller_maximum_command <= 0:
            raise ValueError("Controller maximum command must be positive")
        if not 0 <= self.controller_dead_zone < self.controller_maximum_command:
            raise ValueError("Controller dead zone must be within the command range")
        if not self.data_notice.strip():
            raise ValueError("Drive dynamics data notice must not be empty")


class DriveDynamics:
    """Integrate master-controller commands into a bounded frequency state."""

    def __init__(
        self,
        config: DriveDynamicsConfig,
        minimum_control_frequency_hz: float,
        maximum_control_frequency_hz: float,
    ) -> None:
        self.config = config
        self.minimum_control_frequency_hz = float(minimum_control_frequency_hz)
        self.maximum_control_frequency_hz = float(maximum_control_frequency_hz)
        if (
            not math.isfinite(self.minimum_control_frequency_hz)
            or not math.isfinite(self.maximum_control_frequency_hz)
            or self.maximum_control_frequency_hz
            <= self.minimum_control_frequency_hz
        ):
            raise ValueError("Control-frequency limits must be finite and increasing")
        self.dynamic_control_frequency_hz = self.minimum_control_frequency_hz
        self.master_command = 0.0

    @property
    def drive_state(self) -> DriveState:
        if self.master_command > self.config.controller_dead_zone:
            return DriveState.POWERING
        if self.master_command < -self.config.controller_dead_zone:
            return DriveState.BRAKING
        return DriveState.COAST

    def set_frequency(self, control_frequency_hz: float) -> float:
        self.dynamic_control_frequency_hz = clamp_finite(
            control_frequency_hz,
            self.minimum_control_frequency_hz,
            self.maximum_control_frequency_hz,
            "dynamic_control_frequency_hz",
        )
        return self.dynamic_control_frequency_hz

    def set_master_command(self, command: float) -> DriveState:
        self.master_command = clamp_finite(
            command,
            -self.config.controller_maximum_command,
            self.config.controller_maximum_command,
            "master_command",
        )
        return self.drive_state

    def advance(self, delta_seconds: float) -> float:
        delta = float(delta_seconds)
        if not math.isfinite(delta) or delta < 0:
            raise ValueError("delta_seconds must be finite and non-negative")
        command_ratio = abs(self.master_command) / self.config.controller_maximum_command
        if self.drive_state is DriveState.POWERING:
            change = (
                self.config.power_frequency_rate_hz_per_s
                * command_ratio
                * delta
            )
        elif self.drive_state is DriveState.BRAKING:
            change = -(
                self.config.brake_frequency_rate_hz_per_s
                * command_ratio
                * delta
            )
        else:
            change = 0.0
        return self.set_frequency(self.dynamic_control_frequency_hz + change)
