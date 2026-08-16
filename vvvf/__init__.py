"""Core package for VVVF GTO Simulator MK3."""

from .dynamics import DriveDynamics, DriveDynamicsConfig
from .frequency import LinearFrequencyMapper
from .loudness import LoudnessCompensationConfig, MonitorLoudnessCompensator
from .audio import AudioOutput, AudioSynthesizer
from .model import AudioModel, DriveState, InputMode, InterpolationType, ModulationMode
from .modulation import VVVFModulator, WaveformBlock
from .motor_emulator import MotorAcousticEmulator, MotorEmulatorConfig
from .motor_model import LinearMotorFrequencyModel
from .offline_renderer import OfflineRenderConfig, OfflineRenderer
from .profile import VVVFProfile, load_profile
from .run_export import ExportedRun, ValidationSummary, export_full_cycle
from .scenario import FullCycleScenario, ScenarioPhase, ScenarioRunner
from .spectrogram import generate_spectrogram
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
    "OfflineRenderConfig",
    "OfflineRenderer",
    "FullCycleScenario",
    "ScenarioPhase",
    "ScenarioRunner",
    "generate_spectrogram",
    "SimulationSnapshot",
    "SimulationState",
    "VVVFProfile",
    "ExportedRun",
    "ValidationSummary",
    "export_full_cycle",
    "VVVFModulator",
    "WaveformBlock",
    "load_profile",
]
