"""Compare Legacy Switching and Motor Emulator outputs as CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from vvvf.audio import AudioSynthesizer
from vvvf.model import AudioModel, InputMode
from vvvf.profile import VVVFProfile, load_profile
from vvvf.state import SimulationSnapshot, SimulationState


FREQUENCIES = (5, 8, 10, 15, 20, 30, 40, 50, 60, 75, 90, 106)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Motor Emulator A/B RMS sweep")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(__file__).parents[1] / "profiles" / "mck01c_research.json",
    )
    return parser.parse_args()


def render(
    profile: VVVFProfile, snapshot: SimulationSnapshot, audio_model: AudioModel
) -> tuple[float, float, bool]:
    synthesizer = AudioSynthesizer(profile, master_volume=1.0)
    synthesizer.set_loudness_compensation(False)
    synthesizer.set_audio_model(audio_model)
    for _ in range(15):
        synthesizer.synthesize(snapshot, 4800)
    audio = np.concatenate(
        [synthesizer.synthesize(snapshot, 4800) for _ in range(5)]
    ).astype(np.float64)
    return (
        float(np.sqrt(np.mean(np.square(audio)))),
        float(np.max(np.abs(audio))),
        bool(np.isfinite(audio).all()),
    )


def main() -> int:
    profile = load_profile(parse_args().profile)
    print(
        "control_frequency_hz,mode,pulse_count,profile_amplitude,"
        "legacy_rms,legacy_peak,legacy_finite,motor_rms,motor_peak,motor_finite"
    )
    for frequency in FREQUENCIES:
        state = SimulationState(profile)
        snapshot = state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=frequency,
            throttle_percent=100,
        )
        legacy = render(profile, snapshot, AudioModel.LEGACY_SWITCHING)
        motor = render(profile, snapshot, AudioModel.MOTOR_EMULATOR)
        print(
            f"{frequency},{snapshot.mode},{snapshot.pulse_count},"
            f"{snapshot.amplitude:.6f},{legacy[0]:.8f},{legacy[1]:.8f},"
            f"{str(legacy[2]).lower()},{motor[0]:.8f},{motor[1]:.8f},"
            f"{str(motor[2]).lower()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
