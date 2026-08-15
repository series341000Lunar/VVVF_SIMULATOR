"""Shared enums for the normalized MK2 control model."""

from __future__ import annotations

from enum import StrEnum


class InputMode(StrEnum):
    DIRECT_CONTROL_FREQUENCY = "DIRECT CONTROL FREQ"
    VIRTUAL_VEHICLE_SPEED = "VIRTUAL SPEED"
    DRIVE_SIMULATION = "DRIVE SIMULATION"


class DriveState(StrEnum):
    POWERING = "POWERING"
    COAST = "COAST"
    BRAKING = "BRAKING"


class AudioModel(StrEnum):
    LEGACY_SWITCHING = "LEGACY SWITCHING"
    MOTOR_EMULATOR = "MOTOR EMULATOR"


class ModulationMode(StrEnum):
    ASYNC_PWM = "ASYNC_PWM"
    SYNC_PULSE = "SYNC_PULSE"
    ONE_PULSE = "ONE_PULSE"


class InterpolationType(StrEnum):
    LINEAR = "LINEAR"
    STEP = "STEP"
    HOLD = "HOLD"
