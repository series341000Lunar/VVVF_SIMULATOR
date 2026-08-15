"""MK3 research UI with direct, virtual-speed, and drive-simulation inputs."""

from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QElapsedTimer, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vvvf.audio import AudioOutput
from vvvf.model import DriveState, InputMode, ModulationMode
from vvvf.modulation import VVVFModulator
from vvvf.profile import ProfileError, VVVFProfile, load_profile
from vvvf.state import SimulationSnapshot, SimulationState


class MainWindow(QMainWindow):
    def __init__(self, profile: VVVFProfile) -> None:
        super().__init__()
        self.profile = profile
        self.simulation = SimulationState(profile)
        self.simulation.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            throttle_percent=100,
        )
        self._latest_snapshot = self.simulation.snapshot()
        self.preview_modulator = VVVFModulator()
        self.audio_output = AudioOutput(profile, lambda: self._latest_snapshot)
        self.status_labels: dict[str, QLabel] = {}
        self._listed_drive_state: str | None = None

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.setWindowTitle("VVVF GTO Simulator MK3 — Drive Dynamics")
        self.setMinimumSize(1120, 760)
        self._build_ui()
        self._apply_control_mode()
        self._refresh(self._latest_snapshot)

        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 16, 18, 18)
        root_layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("VVVF GTO Simulator MK3")
        title_font = QFont()
        title_font.setPointSize(19)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch(1)
        self.reload_button = QPushButton("Reload Profile")
        header.addWidget(self.reload_button)
        root_layout.addLayout(header)

        self.profile_label = QLabel(
            f"Profile: {self.profile.name} · schema v{self.profile.schema_version} · "
            f"evidence: {self.profile.evidence_level}"
        )
        root_layout.addWidget(self.profile_label)
        self.notice_label = QLabel(self.profile.data_notice)
        self.notice_label.setObjectName("profileNotice")
        self.notice_label.setWordWrap(True)
        root_layout.addWidget(self.notice_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)
        splitter.addWidget(left)

        controls = QGroupBox("Input and Drive Controls")
        controls_layout = QFormLayout(controls)
        self.input_mode_combo = QComboBox()
        input_modes = list(InputMode)
        if self.profile.drive_dynamics is None:
            input_modes.remove(InputMode.DRIVE_SIMULATION)
        self.input_mode_combo.addItems([mode.value for mode in input_modes])
        controls_layout.addRow("Input Mode", self.input_mode_combo)

        self.direct_frequency_value = QLabel("0.0 Hz")
        direct_row = QHBoxLayout()
        self.direct_frequency_slider = QSlider(Qt.Orientation.Horizontal)
        self.direct_frequency_slider.setRange(
            0, int(round(self.profile.maximum_control_frequency_hz * 10))
        )
        self.direct_frequency_slider.setSingleStep(1)
        self.direct_frequency_slider.setPageStep(10)
        self.direct_frequency_slider.setAccessibleName("Direct control frequency")
        self.direct_frequency_spin = QDoubleSpinBox()
        self.direct_frequency_spin.setRange(
            self.profile.minimum_control_frequency_hz,
            self.profile.maximum_control_frequency_hz,
        )
        self.direct_frequency_spin.setDecimals(1)
        self.direct_frequency_spin.setSingleStep(0.1)
        self.direct_frequency_spin.setSuffix(" Hz")
        direct_row.addWidget(self.direct_frequency_slider, 1)
        direct_row.addWidget(self.direct_frequency_spin)
        controls_layout.addRow("Direct Control Frequency", direct_row)

        self.speed_value = QLabel("0.0 km/h")
        speed_row = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(0, int(round(self.profile.maximum_speed * 10)))
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setPageStep(50)
        self.speed_slider.setAccessibleName("Virtual vehicle speed")
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_value)
        controls_layout.addRow("Virtual Vehicle Speed", speed_row)

        self.throttle_value = QLabel("100 %")
        throttle_row = QHBoxLayout()
        self.throttle_slider = QSlider(Qt.Orientation.Horizontal)
        self.throttle_slider.setRange(0, 100)
        self.throttle_slider.setValue(100)
        self.throttle_slider.setPageStep(5)
        throttle_row.addWidget(self.throttle_slider, 1)
        throttle_row.addWidget(self.throttle_value)
        controls_layout.addRow("Command Level", throttle_row)

        self.master_command_value = QLabel("0 · COAST")
        master_row = QHBoxLayout()
        master_brake_label = QLabel("BRAKE")
        self.master_controller_slider = QSlider(Qt.Orientation.Horizontal)
        maximum_command = (
            100
            if self.profile.drive_dynamics is None
            else int(round(self.profile.drive_dynamics.controller_maximum_command))
        )
        self.master_controller_slider.setRange(-maximum_command, maximum_command)
        self.master_controller_slider.setValue(0)
        self.master_controller_slider.setPageStep(10)
        self.master_controller_slider.setAccessibleName("Master controller")
        master_power_label = QLabel("POWER")
        master_row.addWidget(master_brake_label)
        master_row.addWidget(self.master_controller_slider, 1)
        master_row.addWidget(master_power_label)
        master_row.addWidget(self.master_command_value)
        controls_layout.addRow("Master Controller", master_row)

        self.drive_state_combo = QComboBox()
        self.drive_state_combo.addItems([state.value for state in DriveState])
        controls_layout.addRow("Drive State", self.drive_state_combo)
        left_layout.addWidget(controls)

        status = QGroupBox("Current Normalized State")
        status_layout = QFormLayout(status)
        status_fields = (
            ("input", "Input Mode"),
            ("speed", "Vehicle Speed"),
            ("control", "Control Frequency"),
            ("master", "Master Command"),
            ("drive", "Drive State"),
            ("mode", "Modulation Mode"),
            ("carrier", "Carrier Frequency"),
            ("pulse", "Pulse Count"),
            ("amplitude", "Amplitude"),
            ("fundamental", "Fundamental Frequency"),
            ("audio", "Audio Output State"),
        )
        for key, label in status_fields:
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.status_labels[key] = value
            status_layout.addRow(label, value)
        self.status_labels["electrical"] = self.status_labels["control"]
        self.status_labels["modulation"] = self.status_labels["amplitude"]
        left_layout.addWidget(status)

        audio = QGroupBox("Audio Output")
        audio_layout = QFormLayout(audio)
        volume_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(20)
        self.volume_value = QLabel("20 %")
        volume_row.addWidget(self.volume_slider, 1)
        volume_row.addWidget(self.volume_value)
        audio_layout.addRow("Master Volume", volume_row)
        loudness_row = QHBoxLayout()
        self.loudness_checkbox = QCheckBox("ON")
        self.loudness_checkbox.setChecked(
            self.audio_output.loudness_compensation_enabled
        )
        self.monitor_gain_value = QLabel("+0.0 dB")
        loudness_row.addWidget(self.loudness_checkbox)
        loudness_row.addStretch(1)
        loudness_row.addWidget(QLabel("Monitor Gain"))
        loudness_row.addWidget(self.monitor_gain_value)
        audio_layout.addRow("Loudness Compensation", loudness_row)
        buttons = QHBoxLayout()
        self.start_audio_button = QPushButton("START AUDIO")
        self.stop_audio_button = QPushButton("STOP AUDIO")
        buttons.addWidget(self.start_audio_button)
        buttons.addWidget(self.stop_audio_button)
        audio_layout.addRow(buttons)
        left_layout.addWidget(audio)

        transition_group = QGroupBox("Profile Transitions (active row highlighted)")
        transition_layout = QVBoxLayout(transition_group)
        self.transition_list = QListWidget()
        transition_layout.addWidget(self.transition_list)
        left_layout.addWidget(transition_group, 1)

        self.mapping_notice = QLabel(self.profile.frequency_mapper.data_notice)
        self.mapping_notice.setObjectName("mappingNotice")
        self.mapping_notice.setWordWrap(True)
        left_layout.addWidget(self.mapping_notice)
        self.dynamics_notice = QLabel(
            "Drive simulation unavailable for this profile"
            if self.profile.drive_dynamics is None
            else self.profile.drive_dynamics.data_notice
        )
        self.dynamics_notice.setObjectName("dynamicsNotice")
        self.dynamics_notice.setWordWrap(True)
        left_layout.addWidget(self.dynamics_notice)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.waveform_plot = pg.PlotWidget(title="U Reference and U Switching")
        self.waveform_plot.setLabel("bottom", "Time", units="ms")
        self.waveform_plot.setLabel("left", "Normalized")
        self.waveform_plot.showGrid(x=True, y=True, alpha=0.2)
        self.reference_curve = self.waveform_plot.plot(
            pen=pg.mkPen("#2563eb", width=2), name="U reference"
        )
        self.switching_curve = self.waveform_plot.plot(
            pen=pg.mkPen("#dc2626", width=1), name="U switching"
        )
        self.waveform_plot.addLegend()
        right_layout.addWidget(self.waveform_plot, 1)

        self.spectrum_plot = pg.PlotWidget(title="Switching Excitation FFT")
        self.spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
        self.spectrum_plot.setLabel("left", "Magnitude", units="dB")
        self.spectrum_plot.setXRange(0, 6000)
        self.spectrum_plot.setYRange(-100, 5)
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.2)
        self.spectrum_curve = self.spectrum_plot.plot(
            pen=pg.mkPen("#7c3aed", width=1.5)
        )
        right_layout.addWidget(self.spectrum_plot, 1)
        splitter.addWidget(right)
        splitter.setSizes([430, 680])

        root.setStyleSheet(
            "QGroupBox { font-weight: 600; margin-top: 7px; padding-top: 9px; }"
            "QLabel#profileNotice { color: #9a3412; font-weight: 700; "
            "background: #fff7ed; border: 1px solid #fdba74; padding: 7px; }"
            "QLabel#mappingNotice { color: #854d0e; background: #fefce8; "
            "border: 1px solid #fde047; padding: 6px; }"
            "QLabel#dynamicsNotice { color: #7c2d12; background: #fff7ed; "
            "border: 1px solid #fdba74; padding: 6px; }"
        )
        self.setCentralWidget(root)

        self.input_mode_combo.currentTextChanged.connect(self._input_mode_changed)
        self.direct_frequency_slider.valueChanged.connect(self._direct_slider_changed)
        self.direct_frequency_spin.valueChanged.connect(self._direct_spin_changed)
        self.speed_slider.valueChanged.connect(self._controls_changed)
        self.throttle_slider.valueChanged.connect(self._controls_changed)
        self.master_controller_slider.valueChanged.connect(self._master_changed)
        self.drive_state_combo.currentTextChanged.connect(self._controls_changed)
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.loudness_checkbox.toggled.connect(self._loudness_changed)
        self.start_audio_button.clicked.connect(self._start_audio)
        self.stop_audio_button.clicked.connect(self._stop_audio)
        self.reload_button.clicked.connect(self._reload_profile)

    def _input_mode_changed(self, *_args: object) -> None:
        self._apply_control_mode()
        self._controls_changed()

    def _apply_control_mode(self) -> None:
        direct = (
            self.input_mode_combo.currentText()
            == InputMode.DIRECT_CONTROL_FREQUENCY.value
        )
        virtual_speed = (
            self.input_mode_combo.currentText()
            == InputMode.VIRTUAL_VEHICLE_SPEED.value
        )
        drive_simulation = (
            self.input_mode_combo.currentText() == InputMode.DRIVE_SIMULATION.value
        )
        self.direct_frequency_slider.setEnabled(direct)
        self.direct_frequency_spin.setEnabled(direct)
        self.speed_slider.setEnabled(virtual_speed)
        self.throttle_slider.setEnabled(not drive_simulation)
        self.master_controller_slider.setEnabled(drive_simulation)
        self.drive_state_combo.setEnabled(not drive_simulation)

    def _direct_slider_changed(self, value: int) -> None:
        with QSignalBlocker(self.direct_frequency_spin):
            self.direct_frequency_spin.setValue(value / 10.0)
        self._controls_changed()

    def _direct_spin_changed(self, value: float) -> None:
        with QSignalBlocker(self.direct_frequency_slider):
            self.direct_frequency_slider.setValue(int(round(value * 10)))
        self._controls_changed()

    def _master_changed(self, value: int) -> None:
        self._update_master_command_label(float(value))
        self._controls_changed()

    def _update_master_command_label(self, command: float) -> None:
        dynamics = self.profile.drive_dynamics
        dead_zone = 0.0 if dynamics is None else dynamics.controller_dead_zone
        if command > dead_zone:
            state = DriveState.POWERING.value
        elif command < -dead_zone:
            state = DriveState.BRAKING.value
        else:
            state = DriveState.COAST.value
        self.master_command_value.setText(f"{command:+.0f} · {state}")

    def _controls_changed(self, *_args: object) -> None:
        snapshot = self.simulation.set_controls(
            vehicle_speed_kmh=self.speed_slider.value() / 10.0,
            direct_control_frequency_hz=self.direct_frequency_spin.value(),
            input_mode=self.input_mode_combo.currentText(),
            throttle_percent=self.throttle_slider.value(),
            drive_state=self.drive_state_combo.currentText(),
            master_command=self.master_controller_slider.value(),
        )
        if snapshot.input_mode == InputMode.DRIVE_SIMULATION.value:
            with QSignalBlocker(self.drive_state_combo):
                self.drive_state_combo.setCurrentText(snapshot.drive_state)
        self._latest_snapshot = snapshot
        self._refresh(snapshot)

    def _volume_changed(self, value: int) -> None:
        self.volume_value.setText(f"{value:d} %")
        self.audio_output.set_master_volume(value / 100.0)

    def _loudness_changed(self, enabled: bool) -> None:
        self.loudness_checkbox.setText("ON" if enabled else "OFF")
        self.audio_output.set_loudness_compensation(enabled)
        self.monitor_gain_value.setText(
            f"{self.audio_output.monitor_gain_db:+.1f} dB"
        )

    def _start_audio(self) -> None:
        try:
            self.audio_output.start()
        except Exception as exc:
            QMessageBox.warning(self, "Audio output error", str(exc))
        self._refresh(self._latest_snapshot)

    def _stop_audio(self) -> None:
        self.audio_output.stop()
        self._refresh(self._latest_snapshot)

    def _reload_profile(self) -> None:
        try:
            new_profile = load_profile(self.profile.source_path)
        except (OSError, ProfileError) as exc:
            QMessageBox.critical(self, "Profile reload error", str(exc))
            return
        self.audio_output.stop()
        self.profile = new_profile
        self.simulation = SimulationState(new_profile)
        self.preview_modulator = VVVFModulator()
        self.audio_output = AudioOutput(new_profile, lambda: self._latest_snapshot)
        self.direct_frequency_slider.setMaximum(
            int(round(new_profile.maximum_control_frequency_hz * 10))
        )
        self.direct_frequency_spin.setRange(
            new_profile.minimum_control_frequency_hz,
            new_profile.maximum_control_frequency_hz,
        )
        self.speed_slider.setMaximum(int(round(new_profile.maximum_speed * 10)))
        current_input_mode = self.input_mode_combo.currentText()
        available_input_modes = list(InputMode)
        if new_profile.drive_dynamics is None:
            available_input_modes.remove(InputMode.DRIVE_SIMULATION)
        available_input_values = [mode.value for mode in available_input_modes]
        with QSignalBlocker(self.input_mode_combo):
            self.input_mode_combo.clear()
            self.input_mode_combo.addItems(available_input_values)
            self.input_mode_combo.setCurrentText(
                current_input_mode
                if current_input_mode in available_input_values
                else InputMode.DIRECT_CONTROL_FREQUENCY.value
            )
        maximum_command = (
            100
            if new_profile.drive_dynamics is None
            else int(round(new_profile.drive_dynamics.controller_maximum_command))
        )
        self.master_controller_slider.setRange(-maximum_command, maximum_command)
        self.profile_label.setText(
            f"Profile: {new_profile.name} · schema v{new_profile.schema_version} · "
            f"evidence: {new_profile.evidence_level}"
        )
        self.notice_label.setText(new_profile.data_notice)
        self.mapping_notice.setText(new_profile.frequency_mapper.data_notice)
        self.dynamics_notice.setText(
            "Drive simulation unavailable for this profile"
            if new_profile.drive_dynamics is None
            else new_profile.drive_dynamics.data_notice
        )
        self.audio_output.set_master_volume(self.volume_slider.value() / 100.0)
        self.audio_output.set_loudness_compensation(
            self.loudness_checkbox.isChecked()
        )
        self._listed_drive_state = None
        self._apply_control_mode()
        self._controls_changed()

    def _tick(self) -> None:
        elapsed_seconds = max(self._elapsed.restart(), 0) / 1000.0
        snapshot = self.simulation.advance_time(elapsed_seconds)
        self._latest_snapshot = snapshot
        self._refresh(snapshot)

    def _refresh(self, snapshot: SimulationSnapshot) -> None:
        self.speed_value.setText(f"{snapshot.vehicle_speed_kmh:.1f} km/h")
        self.direct_frequency_value.setText(
            f"{snapshot.direct_control_frequency_hz:.1f} Hz"
        )
        self.throttle_value.setText(f"{snapshot.throttle_percent:d} %")
        self._update_master_command_label(snapshot.master_command)
        if snapshot.input_mode == InputMode.DRIVE_SIMULATION.value:
            with QSignalBlocker(self.speed_slider):
                self.speed_slider.setValue(
                    int(round(snapshot.vehicle_speed_kmh * 10.0))
                )
        self.status_labels["input"].setText(snapshot.input_mode)
        self.status_labels["speed"].setText(f"{snapshot.vehicle_speed_kmh:.1f} km/h")
        self.status_labels["control"].setText(f"{snapshot.control_frequency_hz:.2f} Hz")
        self.status_labels["master"].setText(f"{snapshot.master_command:+.0f}")
        self.status_labels["drive"].setText(snapshot.drive_state)
        self.status_labels["mode"].setText(snapshot.mode)
        self.status_labels["carrier"].setText(
            "—"
            if snapshot.carrier_frequency_hz is None
            else f"{snapshot.carrier_frequency_hz:.1f} Hz"
        )
        self.status_labels["pulse"].setText(
            "—" if snapshot.pulse_count is None else str(snapshot.pulse_count)
        )
        self.status_labels["amplitude"].setText(f"{snapshot.amplitude * 100.0:.1f} %")
        self.status_labels["fundamental"].setText(
            f"{snapshot.fundamental_frequency_hz:.2f} Hz"
        )
        self.status_labels["audio"].setText(self.audio_output.state)
        self.monitor_gain_value.setText(
            f"{self.audio_output.monitor_gain_db:+.1f} dB"
        )
        self._update_transitions(snapshot)
        self._update_plots(snapshot)

    def _update_transitions(self, snapshot: SimulationSnapshot) -> None:
        if self._listed_drive_state != snapshot.drive_state:
            self.transition_list.clear()
            if snapshot.drive_state == DriveState.COAST.value:
                coast = self.profile.coast
                self.transition_list.addItem(
                    f"COAST | {coast.pulse_count}P | hold frequency | "
                    f"decay {coast.decay_seconds:.2f}s (tuning)"
                )
            else:
                pattern = self.profile.patterns[DriveState(snapshot.drive_state)]
                for region in pattern.regions:
                    label = (
                        f"ASYNC {region.carrier_frequency_hz:g} Hz"
                        if region.mode is ModulationMode.ASYNC_PWM
                        else f"{region.pulse_count}P"
                    )
                    self.transition_list.addItem(
                        f"{label:<14} {region.control_frequency_start_hz:5.1f} – "
                        f"{region.control_frequency_end_hz:5.1f} Hz"
                    )
            self._listed_drive_state = snapshot.drive_state
        if snapshot.drive_state == DriveState.COAST.value:
            self.transition_list.setCurrentRow(0)
            return
        pattern = self.profile.patterns[DriveState(snapshot.drive_state)]
        for index, region in enumerate(pattern.regions):
            if (
                region.control_frequency_start_hz == snapshot.region_start_hz
                and region.control_frequency_end_hz == snapshot.region_end_hz
            ):
                self.transition_list.setCurrentRow(index)
                break

    def _update_plots(self, snapshot: SimulationSnapshot) -> None:
        if snapshot.mode == "COAST":
            self.reference_curve.setData([], [])
            self.switching_curve.setData([], [])
            self.spectrum_curve.setData([], [])
            return
        block = self.preview_modulator.generate(
            2048,
            control_frequency_hz=snapshot.control_frequency_hz,
            mode=ModulationMode(snapshot.mode),
            carrier_frequency_hz=snapshot.carrier_frequency_hz,
            pulse_count=snapshot.pulse_count,
            amplitude=snapshot.amplitude,
            advance_phase=False,
        )
        time_ms = block.time_seconds * 1000.0
        self.reference_curve.setData(time_ms, block.references[0])
        self.switching_curve.setData(time_ms, block.switching[0])
        windowed = block.excitation * np.hanning(len(block.excitation))
        magnitude = np.abs(np.fft.rfft(windowed)) / max(len(windowed), 1)
        magnitude_db = 20.0 * np.log10(np.maximum(magnitude, 1e-5))
        frequencies = np.fft.rfftfreq(len(windowed), d=1.0 / 48_000.0)
        visible = frequencies <= 6000.0
        self.spectrum_curve.setData(frequencies[visible], magnitude_db[visible])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        self.audio_output.stop()
        super().closeEvent(event)
