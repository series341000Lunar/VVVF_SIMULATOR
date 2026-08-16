"""Generate an offline spectrogram from the canonical exported WAV."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

from .offline_renderer import StateRecord, TransitionEvent
from .scenario import ScenarioPhase


def generate_spectrogram(
    wav_path: Path,
    output_path: Path,
    state_records: tuple[StateRecord, ...],
    events: tuple[TransitionEvent, ...],
    *,
    maximum_frequency_hz: float = 6_000.0,
) -> Path:
    """Render a PNG from the exact mono WAV that the user will hear."""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    sample_rate, audio = wavfile.read(wav_path)
    if audio.ndim != 1:
        raise ValueError("Canonical spectrogram input must be mono")
    if np.issubdtype(audio.dtype, np.integer):
        scale = float(max(abs(np.iinfo(audio.dtype).min), np.iinfo(audio.dtype).max))
        normalized = audio.astype(np.float64) / scale
    else:
        normalized = audio.astype(np.float64)
    if not np.isfinite(normalized).all():
        raise ValueError("Spectrogram WAV contains non-finite samples")
    frequencies, times, magnitude = signal.spectrogram(
        normalized,
        fs=sample_rate,
        window="hann",
        nperseg=4096,
        noverlap=3072,
        detrend=False,
        scaling="spectrum",
        mode="magnitude",
    )
    visible = frequencies <= min(maximum_frequency_hz, sample_rate / 2.0)
    magnitude_db = 20.0 * np.log10(np.maximum(magnitude[visible], 1e-8))
    upper_db = float(np.max(magnitude_db)) if magnitude_db.size else 0.0

    figure, axis = plt.subplots(figsize=(14, 6))
    figure.subplots_adjust(left=0.075, right=0.89, bottom=0.13, top=0.90)
    image = axis.pcolormesh(
        times,
        frequencies[visible],
        magnitude_db,
        shading="auto",
        cmap="magma",
        vmin=upper_db - 80.0,
        vmax=upper_db,
    )
    phase_colors = {
        ScenarioPhase.POWERING.value: "#22c55e",
        ScenarioPhase.COAST.value: "#3b82f6",
        ScenarioPhase.BRAKING.value: "#f97316",
    }
    duration = len(normalized) / sample_rate
    for phase in ScenarioPhase:
        phase_times = [
            record.time_s
            for record in state_records
            if record.scenario_phase == phase.value
        ]
        if not phase_times:
            continue
        start = min(phase_times)
        later_starts = [
            record.time_s
            for record in state_records
            if record.time_s > start and record.scenario_phase != phase.value
        ]
        end = min(later_starts) if later_starts else duration
        axis.axvspan(start, end, color=phase_colors[phase.value], alpha=0.08)
        axis.text(
            (start + end) / 2.0,
            maximum_frequency_hz * 0.93,
            phase.value,
            color="white",
            fontsize=9,
            fontweight="bold",
            horizontalalignment="center",
            verticalalignment="top",
            bbox={"facecolor": "black", "alpha": 0.35, "edgecolor": "none"},
        )
    modulation_events = [event for event in events if event.event_type == "MODULATION"]
    for index, event in enumerate(modulation_events):
        axis.axvline(event.time_s, color="white", linewidth=0.6, alpha=0.6)
        axis.text(
            event.time_s,
            maximum_frequency_hz * (0.82 if index % 2 else 0.88),
            event.current_value,
            color="white",
            fontsize=6,
            rotation=90,
            horizontalalignment="right",
            verticalalignment="top",
        )
    axis.set_xlim(0.0, duration)
    axis.set_ylim(0.0, maximum_frequency_hz)
    axis.set_xlabel("Time [s]")
    axis.set_ylabel("Frequency [Hz]")
    axis.set_title("MCK01C Full Cycle — Canonical Motor WAV Spectrogram")
    colorbar = figure.colorbar(image, ax=axis, pad=0.02)
    colorbar.set_label("Magnitude [dB]")
    figure.savefig(output_path, dpi=150)
    plt.close(figure)
    return output_path
