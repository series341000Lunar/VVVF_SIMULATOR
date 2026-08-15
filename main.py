"""Application entry point for VVVF GTO Simulator MK1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VVVF GTO Simulator MK1")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(__file__).resolve().parent / "profiles" / "mck01c_research.json",
        help="Path to a VVVF JSON profile",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print(
            "PySide6 is not installed. Create a virtual environment and run "
            "'pip install -r requirements.txt'.",
            file=sys.stderr,
        )
        return 2

    from ui.main_window import MainWindow
    from vvvf.profile import ProfileError, load_profile

    app = QApplication(sys.argv)
    app.setApplicationName("VVVF GTO Simulator MK1")

    try:
        profile = load_profile(args.profile)
    except (OSError, ProfileError) as exc:
        QMessageBox.critical(None, "Profile error", str(exc))
        return 1

    window = MainWindow(profile)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
