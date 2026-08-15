"""Print a deterministic Legacy Audio RMS sweep as CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from vvvf.audio import AudioSynthesizer
from vvvf.model import InputMode
from vvvf.profile import VVVFProfile, load_profile
from vvvf.state import SimulationSnapshot, SimulationState


DEFAULT_FREQUENCIES = (2, 5, 8, 10, 15, 20, 30, 40, 50, 60, 75, 90, 106)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Legacy Audio loudness RMS sweep")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(__file__).parents[1] / "profiles" / "mck01c_research.json",
    )
    return parser.parse_args()


def render(
    profile: VVVFProfile,
    snapshot: SimulationSnapshot,
    *,
    compensation_enabled: bool,
) -> tuple[float, float, float]:
    synthesizer = AudioSynthesizer(profile, master_volume=1.0)
    synthesizer.set_loudness_compensation(compensation_enabled)
    for _ in range(15):
        synthesizer.synthesize(snapshot, 4800)
    audio = np.concatenate(
        [synthesizer.synthesize(snapshot, 4800) for _ in range(5)]
    ).astype(np.float64)
    return (
        float(np.sqrt(np.mean(np.square(audio)))),
        float(np.max(np.abs(audio))),
        synthesizer.monitor_gain_db,
    )


def main() -> int:
    profile = load_profile(parse_args().profile)
    print(
        "control_frequency_hz,mode,pulse_count,profile_amplitude,"
        "raw_rms,raw_peak,compensated_rms,compensated_peak,monitor_gain_db"
    )
    for frequency in DEFAULT_FREQUENCIES:
        state = SimulationState(profile)
        snapshot = state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=frequency,
            throttle_percent=100,
        )
        raw_rms, raw_peak, _ = render(
            profile, snapshot, compensation_enabled=False
        )
        compensated_rms, compensated_peak, gain_db = render(
            profile, snapshot, compensation_enabled=True
        )
        print(
            f"{frequency},{snapshot.mode},{snapshot.pulse_count},"
            f"{snapshot.amplitude:.6f},{raw_rms:.8f},{raw_peak:.8f},"
            f"{compensated_rms:.8f},{compensated_peak:.8f},{gain_db:+.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
