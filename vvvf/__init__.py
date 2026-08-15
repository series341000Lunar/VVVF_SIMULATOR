"""Core package for VVVF GTO Simulator MK2."""

from .frequency import LinearFrequencyMapper
from .audio import AudioOutput, AudioSynthesizer
from .model import DriveState, InputMode, InterpolationType, ModulationMode
from .modulation import VVVFModulator, WaveformBlock
from .motor_model import LinearMotorFrequencyModel
from .profile import VVVFProfile, load_profile
from .state import SimulationSnapshot, SimulationState

__all__ = [
    "AudioOutput",
    "AudioSynthesizer",
    "DriveState",
    "InputMode",
    "InterpolationType",
    "LinearFrequencyMapper",
    "LinearMotorFrequencyModel",
    "ModulationMode",
    "SimulationSnapshot",
    "SimulationState",
    "VVVFProfile",
    "VVVFModulator",
    "WaveformBlock",
    "load_profile",
]
