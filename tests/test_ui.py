from __future__ import annotations

import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from vvvf.model import AudioModel, DriveState, InputMode
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
        self.assertFalse(self.window.master_controller_slider.isEnabled())
        self.assertTrue(self.window.drive_state_combo.isEnabled())

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

    def test_drive_simulation_master_controller_is_authoritative(self) -> None:
        self.window.input_mode_combo.setCurrentText(InputMode.DRIVE_SIMULATION.value)
        self.window.master_controller_slider.setValue(100)
        self.application.processEvents()

        self.assertFalse(self.window.direct_frequency_spin.isEnabled())
        self.assertFalse(self.window.speed_slider.isEnabled())
        self.assertFalse(self.window.throttle_slider.isEnabled())
        self.assertFalse(self.window.drive_state_combo.isEnabled())
        self.assertTrue(self.window.master_controller_slider.isEnabled())
        self.assertEqual(
            self.window.drive_state_combo.currentText(), DriveState.POWERING.value
        )

        powered = self.window.simulation.advance_time(10.0)
        self.window._refresh(powered)
        self.assertEqual(self.window.status_labels["control"].text(), "30.00 Hz")
        self.assertEqual(self.window.status_labels["master"].text(), "+100")
        self.assertEqual(self.window.status_labels["drive"].text(), "POWERING")

        self.window.master_controller_slider.setValue(0)
        coast = self.window.simulation.advance_time(5.0)
        self.window._refresh(coast)
        self.assertEqual(self.window.status_labels["control"].text(), "30.00 Hz")
        self.assertEqual(self.window.status_labels["drive"].text(), "COAST")

        self.window.master_controller_slider.setValue(-100)
        braked = self.window.simulation.advance_time(10.0)
        self.window._refresh(braked)
        self.assertEqual(self.window.status_labels["control"].text(), "0.00 Hz")
        self.assertEqual(self.window.status_labels["drive"].text(), "BRAKING")

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

    def test_loudness_compensation_defaults_on_and_can_toggle(self) -> None:
        self.assertTrue(self.window.loudness_checkbox.isChecked())
        self.assertTrue(self.window.audio_output.loudness_compensation_enabled)
        self.assertRegex(self.window.monitor_gain_value.text(), r"^[+-]\d+\.\d dB$")
        self.window.loudness_checkbox.setChecked(False)
        self.application.processEvents()
        self.assertEqual(self.window.loudness_checkbox.text(), "OFF")
        self.assertFalse(self.window.audio_output.loudness_compensation_enabled)
        self.window.loudness_checkbox.setChecked(True)
        self.application.processEvents()
        self.assertEqual(self.window.loudness_checkbox.text(), "ON")
        self.assertTrue(self.window.audio_output.loudness_compensation_enabled)

    def test_audio_model_defaults_to_motor_and_can_ab_switch(self) -> None:
        self.assertEqual(
            self.window.audio_model_combo.currentText(), AudioModel.MOTOR_EMULATOR.value
        )
        self.assertEqual(
            self.window.status_labels["audio_model"].text(),
            AudioModel.MOTOR_EMULATOR.value,
        )
        self.window.audio_model_combo.setCurrentText(
            AudioModel.LEGACY_SWITCHING.value
        )
        self.application.processEvents()
        self.assertEqual(
            self.window.audio_output.audio_model, AudioModel.LEGACY_SWITCHING
        )
        self.assertEqual(
            self.window.status_labels["audio_model"].text(),
            AudioModel.LEGACY_SWITCHING.value,
        )

    def test_profile_reload_keeps_schema_v2_running(self) -> None:
        self.window.reload_button.click()
        self.application.processEvents()
        self.assertIn("schema v2", self.window.profile_label.text())
        self.assertEqual(self.window.profile.schema_version, 2)

    def test_interactive_auto_run_owns_controls_and_abort_restores_them(self) -> None:
        self.window.run_full_cycle_button.click()
        self.application.processEvents()
        self.assertIsNotNone(self.window._auto_runner)
        self.assertEqual(self.window.auto_test_status.text(), "POWERING")
        self.assertFalse(self.window.input_mode_combo.isEnabled())
        self.assertFalse(self.window.direct_frequency_spin.isEnabled())
        self.assertFalse(self.window.master_controller_slider.isEnabled())
        self.assertFalse(self.window.reload_button.isEnabled())
        self.assertTrue(self.window.abort_auto_test_button.isEnabled())

        self.window.abort_auto_test_button.click()
        self.application.processEvents()
        self.assertIsNone(self.window._auto_runner)
        self.assertEqual(self.window.auto_test_status.text(), "ABORTED")
        self.assertTrue(self.window.input_mode_combo.isEnabled())
        self.assertTrue(self.window.master_controller_slider.isEnabled())
        self.assertTrue(self.window.reload_button.isEnabled())

    def test_offline_render_runs_in_worker_and_reports_output(self) -> None:
        output_path = Path("research/runs/test_full_cycle")

        def fake_export(*_args: object, **kwargs: object) -> SimpleNamespace:
            kwargs["progress"](1.0, "BRAKING")
            return SimpleNamespace(run_directory=output_path)

        with patch("ui.main_window.export_full_cycle", side_effect=fake_export):
            self.window.render_full_cycle_button.click()
            self.assertIsNotNone(self.window._render_thread)
            self.assertFalse(self.window.reload_button.isEnabled())
            for _ in range(200):
                self.application.processEvents()
                if self.window._render_thread is None:
                    break
                QTest.qWait(5)

        self.assertIsNone(self.window._render_thread)
        self.assertEqual(self.window.auto_test_status.text(), "COMPLETE")
        self.assertIn(str(output_path), self.window.auto_test_output.text())
        self.assertTrue(self.window.reload_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
