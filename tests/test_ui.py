from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from vvvf.profile import load_profile


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow(load_profile(PROFILE_PATH))

    def tearDown(self) -> None:
        self.window.close()
        self.application.processEvents()

    def test_controls_update_derived_state_display(self) -> None:
        self.window.speed_slider.setValue(423)
        self.window.throttle_slider.setValue(65)
        self.application.processEvents()

        self.assertEqual(self.window.speed_value.text(), "42.3 km/h")
        self.assertEqual(self.window.status_labels["mode"].text(), "SYNC_PULSE")
        self.assertEqual(self.window.status_labels["pulse"].text(), "15")
        self.assertEqual(self.window.status_labels["carrier"].text(), "—")
        self.assertEqual(self.window.status_labels["electrical"].text(), "38.07 Hz")

    def test_coast_updates_status_without_destroying_speed(self) -> None:
        self.window.speed_slider.setValue(800)
        self.window.throttle_slider.setValue(100)
        self.window.direction_combo.setCurrentText("COAST")
        self.application.processEvents()

        self.assertEqual(self.window.status_labels["speed"].text(), "80.0 km/h")
        self.assertEqual(self.window.status_labels["mode"].text(), "COAST")
        self.assertEqual(self.window.status_labels["modulation"].text(), "0.000")


if __name__ == "__main__":
    unittest.main()
