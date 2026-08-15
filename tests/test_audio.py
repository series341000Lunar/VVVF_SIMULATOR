from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from vvvf.audio import AudioOutput, AudioSynthesizer
from vvvf.model import DriveState, InputMode
from vvvf.profile import load_profile
from vvvf.state import SimulationSnapshot, SimulationState


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class FakeStream:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FailingStream(FakeStream):
    def start(self) -> None:
        raise RuntimeError("simulated device failure")


class AudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(PROFILE_PATH)
        self.state = SimulationState(self.profile)
        self.state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=10.0,
            throttle_percent=100,
        )

    def test_synthesized_audio_is_finite_and_limited(self) -> None:
        audio = AudioSynthesizer(self.profile).synthesize(self.state.snapshot(), 2048)
        self.assertEqual(audio.dtype, np.float32)
        self.assertTrue(np.isfinite(audio).all())
        self.assertLessEqual(float(np.max(np.abs(audio))), 0.95)
        self.assertGreater(float(np.max(np.abs(audio))), 0.0)

    def test_master_volume_is_clamped(self) -> None:
        synthesizer = AudioSynthesizer(self.profile)
        synthesizer.set_master_volume(2.0)
        self.assertEqual(synthesizer.master_volume, 1.0)
        synthesizer.set_master_volume(-1.0)
        self.assertEqual(synthesizer.master_volume, 0.0)

    def _stable_audio(
        self, snapshot: SimulationSnapshot, *, compensation_enabled: bool
    ) -> tuple[np.ndarray, AudioSynthesizer]:
        synthesizer = AudioSynthesizer(self.profile, master_volume=1.0)
        synthesizer.set_loudness_compensation(compensation_enabled)
        for _ in range(10):
            synthesizer.synthesize(snapshot, 4800)
        audio = np.concatenate(
            [synthesizer.synthesize(snapshot, 4800) for _ in range(5)]
        )
        return audio, synthesizer

    def test_zero_frequency_remains_silent_with_compensation(self) -> None:
        snapshot = self.state.set_controls(direct_control_frequency_hz=0.0)
        audio, _ = self._stable_audio(snapshot, compensation_enabled=True)
        self.assertEqual(float(np.max(np.abs(audio))), 0.0)

    def test_compensation_is_finite_and_gain_is_clamped_across_range(self) -> None:
        synthesizer = AudioSynthesizer(self.profile, master_volume=1.0)
        compensator = synthesizer.loudness_compensator
        config = compensator.config
        for frequency in np.linspace(0.0, 106.8, 55):
            snapshot = self.state.set_controls(
                direct_control_frequency_hz=float(frequency),
                drive_state=DriveState.POWERING,
            )
            gain_db = compensator.target_gain_db(
                snapshot.control_frequency_hz,
                snapshot.mode,
                snapshot.pulse_count,
                snapshot.amplitude,
            )
            self.assertTrue(np.isfinite(gain_db))
            self.assertGreaterEqual(gain_db, config.minimum_compensation_db)
            self.assertLessEqual(gain_db, config.maximum_compensation_db)
            audio = synthesizer.synthesize(snapshot, 1024)
            self.assertTrue(np.isfinite(audio).all())

    def test_compensation_reduces_low_to_high_rms_spread(self) -> None:
        raw_db: list[float] = []
        compensated_db: list[float] = []
        for frequency in (10.0, 30.0, 60.0, 100.0):
            snapshot = self.state.set_controls(
                direct_control_frequency_hz=frequency,
                drive_state=DriveState.POWERING,
            )
            raw, _ = self._stable_audio(snapshot, compensation_enabled=False)
            compensated, _ = self._stable_audio(
                snapshot, compensation_enabled=True
            )
            raw_db.append(20.0 * np.log10(np.sqrt(np.mean(np.square(raw)))))
            compensated_db.append(
                20.0 * np.log10(np.sqrt(np.mean(np.square(compensated))))
            )
        self.assertLess(np.ptp(compensated_db), np.ptp(raw_db) * 0.5)

    def test_coast_decay_is_not_normalized_away(self) -> None:
        coast_state = SimulationState(self.profile)
        coast_state.set_controls(
            input_mode=InputMode.DIRECT_CONTROL_FREQUENCY,
            direct_control_frequency_hz=106.8,
            throttle_percent=100,
        )
        synthesizer = AudioSynthesizer(self.profile, master_volume=1.0)
        start = coast_state.set_controls(drive_state=DriveState.COAST)
        start_audio = np.concatenate(
            [synthesizer.synthesize(start, 4800) for _ in range(5)]
        )
        midpoint = coast_state.advance_time(2.0)
        midpoint_audio = np.concatenate(
            [synthesizer.synthesize(midpoint, 4800) for _ in range(5)]
        )
        finished = coast_state.advance_time(2.0)
        synthesizer.synthesize(finished, 4800)
        finished_audio = np.concatenate(
            [synthesizer.synthesize(finished, 4800) for _ in range(4)]
        )
        rms = [
            float(np.sqrt(np.mean(np.square(audio))))
            for audio in (start_audio, midpoint_audio, finished_audio)
        ]
        self.assertGreater(rms[0], rms[1])
        self.assertGreater(rms[1], rms[2])
        self.assertLess(rms[2], 1e-5)

    def test_braking_cutoff_is_not_boosted(self) -> None:
        cutoff = self.state.set_controls(
            direct_control_frequency_hz=7.3,
            drive_state=DriveState.BRAKING,
        )
        silent, _ = self._stable_audio(cutoff, compensation_enabled=True)
        self.assertLess(float(np.max(np.abs(silent))), 1e-7)
        audible = self.state.set_controls(direct_control_frequency_hz=7.5)
        signal, _ = self._stable_audio(audible, compensation_enabled=True)
        self.assertGreater(float(np.sqrt(np.mean(np.square(signal)))), 1e-5)

    def test_compensation_toggle_preserves_stream_lifecycle(self) -> None:
        created: list[FakeStream] = []

        def factory(**kwargs: object) -> FakeStream:
            stream = FakeStream(**kwargs)
            created.append(stream)
            return stream

        output = AudioOutput(self.profile, self.state.snapshot, stream_factory=factory)
        self.assertTrue(output.loudness_compensation_enabled)
        output.start()
        output.set_loudness_compensation(False)
        self.assertFalse(output.loudness_compensation_enabled)
        output.set_loudness_compensation(True)
        self.assertTrue(output.loudness_compensation_enabled)
        self.assertTrue(output.is_running)
        output.stop()
        self.assertTrue(created[0].closed)

    def test_stream_start_stop_releases_device(self) -> None:
        created: list[FakeStream] = []

        def factory(**kwargs: object) -> FakeStream:
            stream = FakeStream(**kwargs)
            created.append(stream)
            return stream

        output = AudioOutput(self.profile, self.state.snapshot, stream_factory=factory)
        output.start()
        self.assertTrue(output.is_running)
        self.assertTrue(created[0].started)
        output.stop()
        self.assertEqual(output.state, "STOPPED")
        self.assertTrue(created[0].stopped)
        self.assertTrue(created[0].closed)

    def test_pulse_count_changes_synthesized_audio(self) -> None:
        pulse_27 = self.state.snapshot()
        pulse_15 = replace(pulse_27, pulse_count=15)
        audio_27 = AudioSynthesizer(self.profile).synthesize(pulse_27, 4096)
        audio_15 = AudioSynthesizer(self.profile).synthesize(pulse_15, 4096)
        self.assertFalse(np.allclose(audio_27, audio_15))

    def test_failed_stream_start_is_closed(self) -> None:
        created: list[FailingStream] = []

        def factory(**kwargs: object) -> FailingStream:
            stream = FailingStream(**kwargs)
            created.append(stream)
            return stream

        output = AudioOutput(self.profile, self.state.snapshot, stream_factory=factory)
        with self.assertRaisesRegex(RuntimeError, "simulated device failure"):
            output.start()
        self.assertTrue(created[0].closed)
        self.assertIn("ERROR", output.state)


if __name__ == "__main__":
    unittest.main()
