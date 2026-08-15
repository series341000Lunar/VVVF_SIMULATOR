from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from vvvf.audio import AudioOutput, AudioSynthesizer
from vvvf.model import InputMode
from vvvf.profile import load_profile
from vvvf.state import SimulationState


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
