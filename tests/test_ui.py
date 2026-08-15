from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from vvvf.model import DriveState, InputMode
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

    def test_direct_control_frequency_is_default_and_precise(self) -> None:
        self.window.direct_frequency_spin.setValue(8.6)
        self.application.processEvents()
        self.assertEqual(
            self.window.input_mode_combo.currentText(),
            InputMode.DIRECT_CONTROL_FREQUENCY.value,
        )
        self.assertEqual(self.window.status_labels["control"].text(), "8.60 Hz")
        self.assertEqual(self.window.status_labels["pulse"].text(), "27")
        self.assertTrue(self.window.direct_frequency_spin.isEnabled())
        self.assertFalse(self.window.speed_slider.isEnabled())

    def test_virtual_speed_routes_through_mapper(self) -> None:
        self.window.input_mode_combo.setCurrentText(
            InputMode.VIRTUAL_VEHICLE_SPEED.value
        )
        self.window.speed_slider.setValue(600)
        self.application.processEvents()
        self.assertEqual(self.window.status_labels["speed"].text(), "60.0 km/h")
        self.assertEqual(self.window.status_labels["control"].text(), "53.40 Hz")
        self.assertEqual(self.window.status_labels["pulse"].text(), "5")
        self.assertTrue(self.window.speed_slider.isEnabled())

    def test_braking_table_and_transition_highlight(self) -> None:
        self.window.direct_frequency_spin.setValue(49.0)
        self.window.drive_state_combo.setCurrentText(DriveState.BRAKING.value)
        self.application.processEvents()
        self.assertEqual(self.window.status_labels["drive"].text(), "BRAKING")
        self.assertEqual(self.window.status_labels["pulse"].text(), "9")
        self.assertEqual(self.window.transition_list.currentRow(), 2)

    def test_coast_uses_three_pulse_and_holds_control_frequency(self) -> None:
        self.window.direct_frequency_spin.setValue(106.8)
        self.window.drive_state_combo.setCurrentText(DriveState.COAST.value)
        self.window.direct_frequency_spin.setValue(20.0)
        self.application.processEvents()
        self.assertEqual(self.window.status_labels["control"].text(), "106.80 Hz")
        self.assertEqual(self.window.status_labels["pulse"].text(), "3")
        self.assertEqual(self.window.transition_list.currentRow(), 0)

    def test_waveform_and_fft_receive_data(self) -> None:
        self.window.direct_frequency_spin.setValue(10.0)
        self.application.processEvents()
        self.assertGreater(len(self.window.reference_curve.getData()[0]), 100)
        self.assertGreater(len(self.window.spectrum_curve.getData()[0]), 100)

    def test_profile_reload_keeps_schema_v2_running(self) -> None:
        self.window.reload_button.click()
        self.application.processEvents()
        self.assertIn("schema v2", self.window.profile_label.text())
        self.assertEqual(self.window.profile.schema_version, 2)


if __name__ == "__main__":
    unittest.main()
