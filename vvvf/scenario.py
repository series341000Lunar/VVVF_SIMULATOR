"""Deterministic, UI-independent validation scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .model import DriveState, InputMode
from .profile import VVVFProfile
from .state import SimulationSnapshot, SimulationState


class ScenarioPhase(StrEnum):
    POWERING = "POWERING"
    COAST = "COAST"
    BRAKING = "BRAKING"


@dataclass(frozen=True, slots=True)
class ScenarioPhaseDefinition:
    phase: ScenarioPhase
    duration_seconds: float
    master_command: float


@dataclass(frozen=True, slots=True)
class FullCycleScenario:
    """Profile-derived 0 Hz -> maximum -> coast -> 0 Hz scenario."""

    name: str
    minimum_control_frequency_hz: float
    maximum_control_frequency_hz: float
    power_rate_hz_per_s: float
    brake_rate_hz_per_s: float
    coast_duration_s: float
    maximum_master_command: float

    @classmethod
    def from_profile(cls, profile: VVVFProfile) -> "FullCycleScenario":
        dynamics = profile.drive_dynamics
        if dynamics is None:
            raise ValueError("Full-cycle scenario requires profile drive_dynamics")
        return cls(
            name="MCK01C FULL CYCLE",
            minimum_control_frequency_hz=profile.minimum_control_frequency_hz,
            maximum_control_frequency_hz=profile.maximum_control_frequency_hz,
            power_rate_hz_per_s=dynamics.power_frequency_rate_hz_per_s,
            brake_rate_hz_per_s=dynamics.brake_frequency_rate_hz_per_s,
            coast_duration_s=profile.coast.decay_seconds,
            maximum_master_command=dynamics.controller_maximum_command,
        )

    @property
    def frequency_span_hz(self) -> float:
        return self.maximum_control_frequency_hz - self.minimum_control_frequency_hz

    @property
    def powering_duration_s(self) -> float:
        return self.frequency_span_hz / self.power_rate_hz_per_s

    @property
    def braking_duration_s(self) -> float:
        return self.frequency_span_hz / self.brake_rate_hz_per_s

    @property
    def phases(self) -> tuple[ScenarioPhaseDefinition, ...]:
        return (
            ScenarioPhaseDefinition(
                ScenarioPhase.POWERING,
                self.powering_duration_s,
                self.maximum_master_command,
            ),
            ScenarioPhaseDefinition(ScenarioPhase.COAST, self.coast_duration_s, 0.0),
            ScenarioPhaseDefinition(
                ScenarioPhase.BRAKING,
                self.braking_duration_s,
                -self.maximum_master_command,
            ),
        )

    @property
    def total_duration_s(self) -> float:
        return sum(item.duration_seconds for item in self.phases)


class ScenarioRunner:
    """Advance a full cycle with exact phase-boundary state changes."""

    def __init__(self, profile: VVVFProfile, scenario: FullCycleScenario) -> None:
        self.profile = profile
        self.scenario = scenario
        self.state = SimulationState(profile)
        self._phase_index = 0
        self.phase_elapsed_seconds = 0.0
        self.elapsed_seconds = 0.0
        self.complete = False
        self.state.set_controls(
            input_mode=InputMode.DRIVE_SIMULATION,
            dynamic_control_frequency_hz=scenario.minimum_control_frequency_hz,
            master_command=scenario.phases[0].master_command,
            throttle_percent=100,
        )

    @property
    def current_definition(self) -> ScenarioPhaseDefinition:
        return self.scenario.phases[self._phase_index]

    @property
    def phase(self) -> ScenarioPhase:
        return self.current_definition.phase

    @property
    def seconds_until_transition(self) -> float:
        if self.complete:
            return 0.0
        return max(
            self.current_definition.duration_seconds - self.phase_elapsed_seconds,
            0.0,
        )

    def snapshot(self) -> SimulationSnapshot:
        return self.state.snapshot()

    def _finish_current_phase(self) -> None:
        if self.phase is ScenarioPhase.POWERING:
            self.state.set_controls(
                dynamic_control_frequency_hz=self.scenario.maximum_control_frequency_hz
            )
        elif self.phase is ScenarioPhase.BRAKING:
            self.state.set_controls(
                dynamic_control_frequency_hz=self.scenario.minimum_control_frequency_hz
            )
        if self._phase_index == len(self.scenario.phases) - 1:
            self.complete = True
            return
        self._phase_index += 1
        self.phase_elapsed_seconds = 0.0
        self.state.set_controls(master_command=self.current_definition.master_command)

    def advance(self, delta_seconds: float) -> SimulationSnapshot:
        delta = float(delta_seconds)
        if not math.isfinite(delta) or delta < 0:
            raise ValueError("delta_seconds must be finite and non-negative")
        remaining = delta
        epsilon = 1e-12
        while remaining > epsilon and not self.complete:
            step = min(remaining, self.seconds_until_transition)
            if step > epsilon:
                self.state.advance_time(step)
                self.phase_elapsed_seconds += step
                self.elapsed_seconds += step
                remaining -= step
            if self.seconds_until_transition <= epsilon:
                self._finish_current_phase()
        return self.snapshot()
