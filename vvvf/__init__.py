"""Core package for VVVF GTO Simulator MK3."""

from .dynamics import DriveDynamics, DriveDynamicsConfig
from .frequency import LinearFrequencyMapper
from .loudness import LoudnessCompensationConfig, MonitorLoudnessCompensator
from .audio import AudioOutput, AudioSynthesizer
from .model import AudioModel, DriveState, InputMode, InterpolationType, ModulationMode
from .modulation import VVVFModulator, WaveformBlock
from .motor_emulator import MotorAcousticEmulator, MotorEmulatorConfig
from .motor_model import LinearMotorFrequencyModel
from .profile import VVVFProfile, load_profile
from .state import SimulationSnapshot, SimulationState

__all__ = [
    "AudioOutput",
    "AudioSynthesizer",
    "AudioModel",
    "DriveDynamics",
    "DriveDynamicsConfig",
    "DriveState",
    "InputMode",
    "InterpolationType",
    "LinearFrequencyMapper",
    "LinearMotorFrequencyModel",
    "LoudnessCompensationConfig",
    "ModulationMode",
    "MonitorLoudnessCompensator",
    "MotorAcousticEmulator",
    "MotorEmulatorConfig",
    "SimulationSnapshot",
    "SimulationState",
    "VVVFProfile",
    "VVVFModulator",
    "WaveformBlock",
    "load_profile",
]
