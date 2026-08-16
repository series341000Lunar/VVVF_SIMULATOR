from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from PIL import Image

from vvvf.offline_renderer import RenderAborted
from vvvf.profile import load_profile
from vvvf.run_export import STATE_COLUMNS, export_full_cycle


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class FullCycleExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.profile = load_profile(PROFILE_PATH)
        cls.exported = export_full_cycle(
            cls.profile,
            output_root=Path(cls.temporary_directory.name) / "runs",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_wav_is_48khz_mono_pcm_finite_safe_and_non_silent(self) -> None:
        sample_rate, audio = wavfile.read(self.exported.motor_wav)
        self.assertEqual(sample_rate, 48_000)
        self.assertEqual(audio.ndim, 1)
        self.assertEqual(audio.dtype, np.int16)
        self.assertEqual(len(audio), round(75.2 * sample_rate))
        normalized = audio.astype(np.float64) / 32767.0
        self.assertTrue(np.isfinite(normalized).all())
        self.assertLessEqual(float(np.max(np.abs(normalized))), 0.951)
        self.assertGreater(float(np.sqrt(np.mean(np.square(normalized)))), 1e-6)

    def test_state_csv_has_required_columns_and_full_cycle(self) -> None:
        with self.exported.state_csv.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(tuple(rows[0]), STATE_COLUMNS)
        times = np.asarray([float(row["time_s"]) for row in rows])
        frequencies = np.asarray([float(row["control_frequency_hz"]) for row in rows])
        self.assertTrue(np.all(np.diff(times) > 0))
        self.assertAlmostEqual(frequencies[0], 0.0)
        self.assertAlmostEqual(float(np.max(frequencies)), 106.8)
        self.assertAlmostEqual(frequencies[-1], 0.0)
        self.assertEqual(
            {row["scenario_phase"] for row in rows},
            {"POWERING", "COAST", "BRAKING"},
        )
        labels = {
            (
                f"ASYNC {float(row['carrier_frequency_hz']):g} Hz"
                if row["modulation_mode"] == "ASYNC_PWM"
                else f"{row['pulse_count']}P"
            )
            for row in rows
            if row["scenario_phase"] != "COAST"
        }
        self.assertTrue(
            {"ASYNC 365 Hz", "27P", "15P", "9P", "5P", "3P", "1P"}
            <= labels
        )

    def test_events_and_metadata_capture_reproducibility_context(self) -> None:
        with self.exported.events_csv.open(encoding="utf-8", newline="") as stream:
            events = list(csv.DictReader(stream))
        self.assertTrue(any(row["event_type"] == "MODULATION" for row in events))
        self.assertTrue(
            any(row["event_type"] == "SCENARIO_COMPLETE" for row in events)
        )
        metadata = json.loads(self.exported.metadata_json.read_text(encoding="utf-8"))
        expected_hash = hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest()
        self.assertEqual(metadata["profile_sha256"], expected_hash)
        self.assertEqual(metadata["audio_model"], "MOTOR EMULATOR")
        self.assertEqual(metadata["scenario_name"], "MCK01C FULL CYCLE")
        self.assertEqual(metadata["sample_rate"], 48_000)
        self.assertEqual(metadata["motor_force_mix"], 0.97)
        self.assertEqual(metadata["switching_leakage_mix"], 0.03)
        self.assertAlmostEqual(metadata["render_duration_s"], 75.2)
        self.assertTrue(metadata["validation"]["all_passed"])

    def test_automatic_validation_passes(self) -> None:
        validation = self.exported.validation
        self.assertTrue(validation.all_passed)
        self.assertTrue(validation.audio_clipping_free)
        self.assertEqual(validation.audio_clipped_samples, 0)
        self.assertEqual(validation.powering_patterns_found, 7)
        self.assertEqual(validation.braking_patterns_found, 6)
        self.assertLessEqual(validation.duration_mismatch_ms, 0.001)

    def test_spectrogram_png_is_nonempty_and_has_dimensions(self) -> None:
        self.assertIsNotNone(self.exported.spectrogram_png)
        self.assertGreater(self.exported.spectrogram_png.stat().st_size, 10_000)
        with Image.open(self.exported.spectrogram_png) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreaterEqual(image.width, 2_000)
            self.assertGreaterEqual(image.height, 850)
            pixels = np.asarray(image.convert("RGB"))
            self.assertGreater(float(np.mean(pixels[:40])), 240.0)
            self.assertGreater(float(np.mean(pixels[-40:])), 240.0)

    def test_abort_removes_partial_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "runs"
            with self.assertRaises(RenderAborted):
                export_full_cycle(
                    self.profile,
                    output_root=output_root,
                    abort_requested=lambda: True,
                )
            self.assertEqual(list(output_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
