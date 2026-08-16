"""Command-line deterministic full-cycle artifact exporter."""

from __future__ import annotations

import argparse
from pathlib import Path

from vvvf.offline_renderer import OfflineRenderConfig
from vvvf.profile import load_profile
from vvvf.run_export import export_full_cycle


def parse_args() -> argparse.Namespace:
    repository_root = Path(__file__).parents[1]
    parser = argparse.ArgumentParser(description="Render the MCK01C full cycle")
    parser.add_argument(
        "--profile",
        type=Path,
        default=repository_root / "profiles" / "mck01c_research.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=repository_root / "research" / "runs",
    )
    parser.add_argument("--legacy", action="store_true", help="Also render legacy.wav")
    parser.add_argument(
        "--no-loudness", action="store_true", help="Disable monitor compensation"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    last_percent = -1

    def progress(ratio: float, phase: str) -> None:
        nonlocal last_percent
        percent = int(ratio * 100.0)
        if percent // 10 != last_percent // 10:
            print(f"{percent:3d}% {phase}")
            last_percent = percent

    exported = export_full_cycle(
        profile,
        output_root=args.output_root,
        config=OfflineRenderConfig(
            loudness_compensation_enabled=not args.no_loudness
        ),
        include_legacy=args.legacy,
        progress=progress,
    )
    validation = exported.validation
    print(f"Output: {exported.run_directory}")
    print(f"Duration: {validation.wav_duration_s:.3f} s")
    print(
        "Transitions: "
        f"POWERING {validation.powering_patterns_found}/"
        f"{validation.powering_patterns_expected}, "
        f"BRAKING {validation.braking_patterns_found}/"
        f"{validation.braking_patterns_expected}"
    )
    print(f"Audio peak: {validation.audio_peak:.6f}")
    print(f"Validation: {'PASS' if validation.all_passed else 'FAIL'}")
    return 0 if validation.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
