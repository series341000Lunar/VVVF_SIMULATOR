from __future__ import annotations

import csv
import unittest
from pathlib import Path

from vvvf.profile import load_profile


ROOT = Path(__file__).parents[1]
PROFILE_PATH = ROOT / "profiles" / "mck01c_research.json"
OBSERVATIONS_PATH = ROOT / "research" / "observations" / "mck01c_observed.csv"


class ResearchDataTests(unittest.TestCase):
    def test_observations_are_separate_and_linked_to_unverified_profile(self) -> None:
        profile = load_profile(PROFILE_PATH)
        with OBSERVATIONS_PATH.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertGreaterEqual(len(rows), 30)
        self.assertFalse(profile.verified)
        self.assertEqual(
            profile.evidence_level, "observed_from_third_party_recreation"
        )
        self.assertTrue(any(row["state"] == "COAST" for row in rows))
        self.assertTrue(any(row["confidence"] == "APPROXIMATE" for row in rows))

    def test_sources_does_not_invent_missing_video_url(self) -> None:
        sources = (ROOT / "research" / "SOURCES.md").read_text(encoding="utf-8")
        self.assertIn("Exact video URL: not supplied", sources)
        self.assertIn("not be described as Toshiba factory control data", sources)

    def test_raw_media_ignore_policy_is_documented(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("research/raw/*", ignore)
        self.assertIn("*.mp4", ignore)


if __name__ == "__main__":
    unittest.main()
