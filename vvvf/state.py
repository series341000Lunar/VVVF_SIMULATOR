"""UI-independent Stage A simulation state and derived status values."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .motor_model import LinearMotorFrequencyModel
from .profile import VVVFProfile


LOGGER = logging.getLogger("vvvf")
VALID_DIRECTIONS = frozenset({"POWERING", "COAST"})


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    speed_kmh: float
    throttle_percent: int
    direction: str
    electrical_frequency_hz: float
    fundamental_frequency_hz: float
    mode: str
    carrier_hz: float | None
    pulse_count: int | None
    modulation_index: float
    audio_state: str


class SimulationState:
    def __init__(self, profile: VVVFProfile) -> None:
        self.profile = profile
        self.speed_kmh = 0.0
        self.throttle_percent = 0
        self.direction = "POWERING"
        self._motor_model = LinearMotorFrequencyModel(profile.electrical_hz_per_kmh)
        self._last_transition: tuple[str, float | None, int | None] | None = None

    def set_controls(
        self,
        *,
        speed_kmh: float | None = None,
        throttle_percent: int | None = None,
        direction: str | None = None,
    ) -> SimulationSnapshot:
        if speed_kmh is not None:
            self.speed_kmh = min(max(float(speed_kmh), 0.0), self.profile.maximum_speed)
        if throttle_percent is not None:
            self.throttle_percent = min(max(int(throttle_percent), 0), 100)
        if direction is not None:
            if direction not in VALID_DIRECTIONS:
                raise ValueError(f"Unsupported direction/state: {direction}")
            self.direction = direction
        return self.snapshot()

    def snapshot(self) -> SimulationSnapshot:
        electrical_hz = self._motor_model.electrical_frequency(self.speed_kmh)
        if self.direction == "COAST":
            mode = "COAST"
            carrier_hz = None
            pulse_count = None
            modulation_index = 0.0
        else:
            region = self.profile.region_for_speed(self.speed_kmh)
            mode = region.mode
            carrier_hz = region.carrier_hz
            pulse_count = region.pulse_count
            modulation_index = (
                self.throttle_percent / 100.0 * self.profile.maximum_modulation_index
            )

        transition = (mode, carrier_hz, pulse_count)
        if transition != self._last_transition:
            details = []
            if carrier_hz is not None:
                details.append(f"carrier={carrier_hz:g} Hz")
            if pulse_count is not None:
                details.append(f"pulse={pulse_count}P")
            suffix = f" ({', '.join(details)})" if details else ""
            LOGGER.info(
                "[VVVF] %.1f km/h transition -> %s%s", self.speed_kmh, mode, suffix
            )
            self._last_transition = transition

        return SimulationSnapshot(
            speed_kmh=self.speed_kmh,
            throttle_percent=self.throttle_percent,
            direction=self.direction,
            electrical_frequency_hz=electrical_hz,
            fundamental_frequency_hz=electrical_hz,
            mode=mode,
            carrier_hz=carrier_hz,
            pulse_count=pulse_count,
            modulation_index=modulation_index,
            audio_state="NOT IMPLEMENTED (Stage D)",
        )
