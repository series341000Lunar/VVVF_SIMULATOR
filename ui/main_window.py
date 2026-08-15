"""Stage A main window: controls and real-time status only."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vvvf.profile import VVVFProfile
from vvvf.state import SimulationSnapshot, SimulationState


class MainWindow(QMainWindow):
    def __init__(self, profile: VVVFProfile) -> None:
        super().__init__()
        self.profile = profile
        self.simulation = SimulationState(profile)
        self.status_labels: dict[str, QLabel] = {}

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.setWindowTitle("VVVF GTO Simulator MK1 — Stage A")
        self.setMinimumSize(700, 600)
        self._build_ui()
        self._refresh(self.simulation.snapshot())

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        title = QLabel("VVVF GTO Simulator MK1")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        profile_label = QLabel(f"Profile: {self.profile.name}")
        layout.addWidget(profile_label)
        notice = QLabel(self.profile.data_notice)
        notice.setObjectName("profileNotice")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        controls = QGroupBox("Vehicle Controls")
        controls_layout = QFormLayout(controls)

        self.speed_value = QLabel("0.0 km/h")
        speed_row = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(0, int(round(self.profile.maximum_speed * 10)))
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setPageStep(50)
        self.speed_slider.setAccessibleName("Vehicle speed")
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_value)
        controls_layout.addRow("Speed", speed_row)

        self.throttle_value = QLabel("0 %")
        throttle_row = QHBoxLayout()
        self.throttle_slider = QSlider(Qt.Orientation.Horizontal)
        self.throttle_slider.setRange(0, 100)
        self.throttle_slider.setPageStep(5)
        self.throttle_slider.setAccessibleName("Power or throttle")
        throttle_row.addWidget(self.throttle_slider, 1)
        throttle_row.addWidget(self.throttle_value)
        controls_layout.addRow("Power / Throttle", throttle_row)

        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["POWERING", "COAST"])
        controls_layout.addRow("Direction / State", self.direction_combo)
        layout.addWidget(controls)

        status = QGroupBox("Current Simulation State")
        status_layout = QFormLayout(status)
        status_fields = (
            ("speed", "Vehicle Speed"),
            ("throttle", "Throttle"),
            ("electrical", "Motor Electrical Frequency"),
            ("mode", "Current Modulation Mode"),
            ("carrier", "Carrier Frequency"),
            ("pulse", "Pulse Count"),
            ("modulation", "Modulation Index"),
            ("fundamental", "Fundamental Frequency"),
            ("audio", "Audio Output State"),
        )
        for key, label in status_fields:
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.status_labels[key] = value
            status_layout.addRow(label, value)
        layout.addWidget(status)

        stage_note = QLabel(
            "Stage A: external profile loading, vehicle controls, and state display. "
            "PWM, waveform graphs, FFT, and audio are intentionally deferred."
        )
        stage_note.setWordWrap(True)
        layout.addWidget(stage_note)
        layout.addStretch(1)

        root.setStyleSheet(
            "QGroupBox { font-weight: 600; margin-top: 8px; padding-top: 10px; }"
            "QLabel#profileNotice { color: #b45309; font-weight: 700; "
            "background: #fff7ed; border: 1px solid #fdba74; padding: 8px; }"
        )
        self.setCentralWidget(root)

        self.speed_slider.valueChanged.connect(self._controls_changed)
        self.throttle_slider.valueChanged.connect(self._controls_changed)
        self.direction_combo.currentTextChanged.connect(self._controls_changed)

    def _controls_changed(self, *_args: object) -> None:
        snapshot = self.simulation.set_controls(
            speed_kmh=self.speed_slider.value() / 10.0,
            throttle_percent=self.throttle_slider.value(),
            direction=self.direction_combo.currentText(),
        )
        self._refresh(snapshot)

    def _refresh(self, snapshot: SimulationSnapshot) -> None:
        self.speed_value.setText(f"{snapshot.speed_kmh:.1f} km/h")
        self.throttle_value.setText(f"{snapshot.throttle_percent:d} %")
        self.status_labels["speed"].setText(f"{snapshot.speed_kmh:.1f} km/h")
        self.status_labels["throttle"].setText(f"{snapshot.throttle_percent:d} %")
        self.status_labels["electrical"].setText(
            f"{snapshot.electrical_frequency_hz:.2f} Hz"
        )
        self.status_labels["mode"].setText(snapshot.mode)
        self.status_labels["carrier"].setText(
            "—" if snapshot.carrier_hz is None else f"{snapshot.carrier_hz:.1f} Hz"
        )
        self.status_labels["pulse"].setText(
            "—" if snapshot.pulse_count is None else str(snapshot.pulse_count)
        )
        self.status_labels["modulation"].setText(f"{snapshot.modulation_index:.3f}")
        self.status_labels["fundamental"].setText(
            f"{snapshot.fundamental_frequency_hz:.2f} Hz"
        )
        self.status_labels["audio"].setText(snapshot.audio_state)
