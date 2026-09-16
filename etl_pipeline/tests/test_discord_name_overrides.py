import unittest
import sys
from pathlib import Path

# Add src directory to path for imports
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shared_utils import apply_discord_name_overrides  # type: ignore


class TestDiscordNameOverrides(unittest.TestCase):
    def setUp(self):
        self.sample_roster = {
            "metadata": {"generated_at": "2026-09-16T00:00:00Z"},
            "members": [
                {
                    "discord_id": "111222333444555666",
                    "discord_name": "OriginalNick1",
                    "current_rsns": ["MainAcc", "IronAcc", "PureAcc"]
                },
                {
                    "discord_id": "999888777666555444",
                    "discord_name": "OriginalNick2",
                    "current_rsns": ["SoloPlayer"]
                },
                {
                    "discord_id": "'777666555444333222",  # Sheets leading apostrophe
                    "discord_name": "OriginalNick3",
                    "current_rsns": ["AltPlayer"]
                }
            ]
        }

    def test_override_matching_by_id(self):
        overrides = {
            "111222333444555666": "CustomBourkie"
        }
        result = apply_discord_name_overrides(self.sample_roster, overrides)
        member1 = next(m for m in result["members"] if "111222333444555666" in m["discord_id"])
        member2 = next(m for m in result["members"] if "999888777666555444" in m["discord_id"])

        self.assertEqual(member1["discord_name"], "CustomBourkie")
        self.assertEqual(member2["discord_name"], "OriginalNick2")

    def test_sanitization_leading_apostrophes_and_quotes(self):
        # Override key has no quote, but member in roster has leading apostrophe
        overrides = {
            "777666555444333222": "SanitizedLeader"
        }
        result = apply_discord_name_overrides(self.sample_roster, overrides)
        member3 = next(m for m in result["members"] if "777666555444333222" in m["discord_id"])
        self.assertEqual(member3["discord_name"], "SanitizedLeader")

        # Override key has accidental quotes / whitespace
        overrides_quoted = {
            " '111222333444555666' ": "QuotedKeyName"
        }
        result = apply_discord_name_overrides(self.sample_roster, overrides_quoted)
        member1 = next(m for m in result["members"] if "111222333444555666" in m["discord_id"])
        self.assertEqual(member1["discord_name"], "QuotedKeyName")

    def test_empty_and_none_overrides(self):
        # Empty overrides dict
        result = apply_discord_name_overrides(self.sample_roster, {})
        self.assertEqual(result["members"][0]["discord_name"], "OriginalNick1")

        # None overrides
        result = apply_discord_name_overrides(self.sample_roster, None)
        self.assertEqual(result["members"][0]["discord_name"], "OriginalNick1")

    def test_enrichment_resolution_with_override(self):
        import importlib
        import pandas as pd
        enrich_mod = importlib.import_module("4_enrich_roster")

        overrides = {"111222333444555666": "PreferredBourkie"}
        payload = apply_discord_name_overrides(self.sample_roster, overrides)

        df_dummy_events = pd.DataFrame(columns=["Username", "Timestamp"])
        interval_map = enrich_mod.build_interval_map(payload, buffer_hours=24, df_all_events=df_dummy_events)

        # Player 1 has 3 accounts: MainAcc, IronAcc, PureAcc
        now = pd.Timestamp.now(tz="UTC")
        names_to_test = ["MainAcc", "IronAcc", "PureAcc", "SoloPlayer"]
        timestamps = [now, now, now, now]

        sync_config = {"wom_sync_delay_tolerance_days": 35}
        d_ids, d_names = enrich_mod.resolve_names_to_discord(names_to_test, timestamps, interval_map, sync_config)

        # The 3 accounts should all resolve to PreferredBourkie
        self.assertEqual(d_names[0], "PreferredBourkie")
        self.assertEqual(d_names[1], "PreferredBourkie")
        self.assertEqual(d_names[2], "PreferredBourkie")
        # SoloPlayer should resolve to OriginalNick2
        self.assertEqual(d_names[3], "OriginalNick2")


if __name__ == "__main__":
    unittest.main()

