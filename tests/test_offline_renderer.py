from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from vvvf.offline_renderer import OfflineRenderer
from vvvf.profile import load_profile


PROFILE_PATH = Path(__file__).parents[1] / "profiles" / "mck01c_research.json"


class OfflineRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(PROFILE_PATH)

    def test_short_render_is_exactly_deterministic(self) -> None:
        first = OfflineRenderer(self.profile).render(duration_limit_s=0.1)
        second = OfflineRenderer(self.profile).render(duration_limit_s=0.1)
        self.assertEqual(len(first.audio), 4_800)
        self.assertTrue(np.array_equal(first.audio, second.audio))
        self.assertEqual(first.state_records, second.state_records)
        self.assertFalse(first.complete)

    def test_offline_renderer_uses_motor_audio_without_sounddevice(self) -> None:
        result = OfflineRenderer(self.profile).render(duration_limit_s=0.1)
        self.assertEqual(result.audio.dtype, np.float32)
        self.assertTrue(np.isfinite(result.audio).all())
        self.assertEqual(result.state_records[0].audio_model, "MOTOR EMULATOR")
        self.assertEqual(result.state_records[0].time_s, 0.0)


if __name__ == "__main__":
    unittest.main()
