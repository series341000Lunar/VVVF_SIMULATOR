"""UI-independent MK2 input, control-frequency, and drive-state model."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from .dynamics import DriveDynamics
from .frequency import clamp_finite
from .model import DriveState, InputMode
from .profile import ModulationRegion, VVVFProfile


LOGGER = logging.getLogger("vvvf")


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    vehicle_speed_kmh: float
    direct_control_frequency_hz: float
    dynamic_control_frequency_hz: float
    control_frequency_hz: float
    input_mode: str
    throttle_percent: int
    master_command: float
    drive_state: str
    fundamental_frequency_hz: float
    mode: str
    carrier_frequency_hz: float | None
    pulse_count: int | None
    amplitude: float
    audio_state: str
    region_start_hz: float | None
    region_end_hz: float | None
    coast_elapsed_seconds: float

    @property
    def speed_kmh(self) -> float:
        return self.vehicle_speed_kmh

    @property
    def direction(self) -> str:
        return self.drive_state

    @property
    def electrical_frequency_hz(self) -> float:
        return self.control_frequency_hz

    @property
    def carrier_hz(self) -> float | None:
        return self.carrier_frequency_hz

    @property
    def modulation_index(self) -> float:
        return self.amplitude


class SimulationState:
    def __init__(self, profile: VVVFProfile) -> None:
        self.profile = profile
        self.vehicle_speed_kmh = 0.0
        self.direct_control_frequency_hz = 0.0
        self.throttle_percent = 0
        self.input_mode = InputMode.VIRTUAL_VEHICLE_SPEED
        self.drive_state = DriveState.POWERING
        self.drive_dynamics = (
            None
            if profile.drive_dynamics is None
            else DriveDynamics(
                profile.drive_dynamics,
                profile.minimum_control_frequency_hz,
                profile.maximum_control_frequency_hz,
            )
        )
        self._active_region: ModulationRegion | None = None
        self._active_region_state: DriveState | None = None
        self._coast_hold_frequency_hz = 0.0
        self._coast_start_amplitude = 0.0
        self._coast_elapsed_seconds = 0.0
        self._last_transition: tuple[str, str, float | None, int | None] | None = None

    @property
    def speed_kmh(self) -> float:
        return self.vehicle_speed_kmh

    @property
    def direction(self) -> str:
        return self.drive_state.value

    @property
    def dynamic_control_frequency_hz(self) -> float:
        if self.drive_dynamics is None:
            return self.profile.minimum_control_frequency_hz
        return self.drive_dynamics.dynamic_control_frequency_hz

    def _requested_control_frequency(self) -> float:
        if self.input_mode is InputMode.DIRECT_CONTROL_FREQUENCY:
            return self.profile.clamp_control_frequency(self.direct_control_frequency_hz)
        if self.input_mode is InputMode.DRIVE_SIMULATION:
            if self.drive_dynamics is None:
                raise ValueError("This profile does not define drive dynamics")
            return self.drive_dynamics.dynamic_control_frequency_hz
        return self.profile.clamp_control_frequency(
            self.profile.frequency_mapper.map_speed(self.vehicle_speed_kmh)
        )

    def _transition_drive_state(self, next_state: DriveState) -> None:
        if next_state is DriveState.COAST and self.drive_state is not DriveState.COAST:
            frequency = self._requested_control_frequency()
            self._coast_hold_frequency_hz = frequency
            if self.drive_state in self.profile.patterns:
                self._coast_start_amplitude = (
                    self.profile.amplitude_for_control_frequency(
                        frequency, self.drive_state
                    )
                    * self.throttle_percent
                    / 100.0
                )
            else:
                self._coast_start_amplitude = 0.0
            self._coast_elapsed_seconds = 0.0
        if next_state is not self.drive_state:
            self._active_region = None
            self._active_region_state = None
        self.drive_state = next_state

    def _select_region(self, control_frequency_hz: float) -> ModulationRegion:
        candidate = self.profile.region_for_control_frequency(
            control_frequency_hz, self.drive_state
        )
        hysteresis = (
            0.0
            if self.input_mode is InputMode.DIRECT_CONTROL_FREQUENCY
            else self.profile.transition_hysteresis_hz
        )
        previous = self._active_region
        if (
            hysteresis > 0
            and previous is not None
            and self._active_region_state is self.drive_state
            and candidate is not previous
            and previous.control_frequency_start_hz - hysteresis
            <= control_frequency_hz
            <= previous.control_frequency_end_hz + hysteresis
        ):
            return previous
        self._active_region = candidate
        self._active_region_state = self.drive_state
        return candidate

    def set_controls(
        self,
        *,
        vehicle_speed_kmh: float | None = None,
        direct_control_frequency_hz: float | None = None,
        input_mode: InputMode | str | None = None,
        throttle_percent: int | None = None,
        drive_state: DriveState | str | None = None,
        master_command: float | None = None,
        dynamic_control_frequency_hz: float | None = None,
        speed_kmh: float | None = None,
        direction: str | None = None,
    ) -> SimulationSnapshot:
        if speed_kmh is not None:
            vehicle_speed_kmh = speed_kmh
        if direction is not None:
            drive_state = direction
        if vehicle_speed_kmh is not None:
            self.vehicle_speed_kmh = clamp_finite(
                vehicle_speed_kmh,
                self.profile.frequency_mapper.vehicle_speed_min_kmh,
                self.profile.frequency_mapper.vehicle_speed_max_kmh,
                "vehicle_speed_kmh",
            )
        if direct_control_frequency_hz is not None:
            self.direct_control_frequency_hz = self.profile.clamp_control_frequency(
                direct_control_frequency_hz
            )
        requested_before_mode = self._requested_control_frequency()
        if input_mode is not None:
            next_input_mode = InputMode(input_mode)
            if (
                next_input_mode is InputMode.DRIVE_SIMULATION
                and self.input_mode is not InputMode.DRIVE_SIMULATION
            ):
                if self.drive_dynamics is None:
                    raise ValueError("This profile does not define drive dynamics")
                self.drive_dynamics.set_frequency(requested_before_mode)
            self.input_mode = next_input_mode
        if dynamic_control_frequency_hz is not None:
            if self.drive_dynamics is None:
                raise ValueError("This profile does not define drive dynamics")
            self.drive_dynamics.set_frequency(dynamic_control_frequency_hz)
        if master_command is not None:
            if self.drive_dynamics is None:
                raise ValueError("This profile does not define drive dynamics")
            self.drive_dynamics.set_master_command(master_command)
        if throttle_percent is not None:
            if isinstance(throttle_percent, bool):
                raise ValueError("throttle_percent must be an integer")
            self.throttle_percent = min(max(int(throttle_percent), 0), 100)
        if self.input_mode is InputMode.DRIVE_SIMULATION:
            if self.drive_dynamics is None:
                raise ValueError("This profile does not define drive dynamics")
            self.throttle_percent = 100
            next_state = self.drive_dynamics.drive_state
            self.vehicle_speed_kmh = self.profile.frequency_mapper.unmap_control_frequency(
                self.drive_dynamics.dynamic_control_frequency_hz
            )
        else:
            next_state = self.drive_state if drive_state is None else DriveState(drive_state)
        self._transition_drive_state(next_state)
        return self.snapshot()

    def advance_time(self, delta_seconds: float) -> SimulationSnapshot:
        delta = float(delta_seconds)
        if not math.isfinite(delta) or delta < 0:
            raise ValueError("delta_seconds must be finite and non-negative")
        if self.input_mode is InputMode.DRIVE_SIMULATION:
            if self.drive_dynamics is None:
                raise ValueError("This profile does not define drive dynamics")
            if self.drive_state is DriveState.COAST:
                self._coast_elapsed_seconds += delta
            else:
                self.drive_dynamics.advance(delta)
                self.vehicle_speed_kmh = (
                    self.profile.frequency_mapper.unmap_control_frequency(
                        self.drive_dynamics.dynamic_control_frequency_hz
                    )
                )
        elif self.drive_state is DriveState.COAST:
            self._coast_elapsed_seconds += delta
        return self.snapshot()

    def snapshot(self) -> SimulationSnapshot:
        requested_frequency = self._requested_control_frequency()
        if self.drive_state is DriveState.COAST:
            control_frequency = (
                self._coast_hold_frequency_hz
                if self.profile.coast.hold_control_frequency
                else requested_frequency
            )
            mode = (
                "COAST" if self.profile.coast.mode is None else self.profile.coast.mode.value
            )
            carrier_frequency = None
            pulse_count = self.profile.coast.pulse_count
            amplitude = self._coast_start_amplitude * self.profile.coast.envelope_gain(
                self._coast_elapsed_seconds
            )
            region_start = None
            region_end = None
        else:
            control_frequency = requested_frequency
            region = self._select_region(control_frequency)
            mode = region.mode.value
            carrier_frequency = region.carrier_frequency_hz
            pulse_count = region.pulse_count
            amplitude = (
                self.profile.amplitude_for_control_frequency(
                    control_frequency, self.drive_state
                )
                * self.throttle_percent
                / 100.0
            )
            region_start = region.control_frequency_start_hz
            region_end = region.control_frequency_end_hz
        transition = (self.drive_state.value, mode, carrier_frequency, pulse_count)
        if transition != self._last_transition:
            details: list[str] = []
            if carrier_frequency is not None:
                details.append(f"carrier={carrier_frequency:g} Hz")
            if pulse_count is not None:
                details.append(f"pulse={pulse_count}P")
            suffix = f" ({', '.join(details)})" if details else ""
            LOGGER.info(
                "[VVVF] %.1f Hz %s transition -> %s%s",
                control_frequency,
                self.drive_state.value,
                mode,
                suffix,
            )
            self._last_transition = transition
        return SimulationSnapshot(
            vehicle_speed_kmh=self.vehicle_speed_kmh,
            direct_control_frequency_hz=self.direct_control_frequency_hz,
            dynamic_control_frequency_hz=self.dynamic_control_frequency_hz,
            control_frequency_hz=control_frequency,
            input_mode=self.input_mode.value,
            throttle_percent=self.throttle_percent,
            master_command=(
                0.0 if self.drive_dynamics is None else self.drive_dynamics.master_command
            ),
            drive_state=self.drive_state.value,
            fundamental_frequency_hz=control_frequency,
            mode=mode,
            carrier_frequency_hz=carrier_frequency,
            pulse_count=pulse_count,
            amplitude=min(max(amplitude, 0.0), 1.0),
            audio_state="NOT IMPLEMENTED",
            region_start_hz=region_start,
            region_end_hz=region_end,
            coast_elapsed_seconds=self._coast_elapsed_seconds,
        )
