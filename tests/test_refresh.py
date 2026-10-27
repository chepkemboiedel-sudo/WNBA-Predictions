"""Regression checks for refreshing an in-progress playoff forecast."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import fetch_espn
import simulate as S


class RefreshTests(unittest.TestCase):
    def test_finished_series_does_not_request_probabilities(self):
        self.assertEqual(S.sim_series("A", "B", "R1", {}, np.random.default_rng(1),
                                     {"A|B": {"hw": 0, "lw": 2}}), "B")

    def test_three_two_lead_matches_two_remaining_games(self):
        # A needs one win: away win probability .4, then home win probability .7.
        # Its exact title probability is 1 - (.6 * .3) = .82.
        probabilities = {("A", "B", False): .4, ("A", "B", True): .7}
        observed = {"A|B": {"hw": 3, "lw": 2}}
        rng = np.random.default_rng(5)
        rate = sum(S.sim_series("A", "B", "FINALS", probabilities, rng, observed) == "A"
                   for _ in range(20000)) / 20000
        self.assertAlmostEqual(rate, .82, delta=.015)

    def test_refresh_preserves_cache_when_scoreboard_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "games_2026.csv"
            cache.write_text("previous-cache", encoding="utf-8")
            with patch.object(fetch_espn, "DATA_DIR", directory), \
                 patch.object(fetch_espn, "_game_dates_for_season", return_value=["20261027"]), \
                 patch.object(fetch_espn, "_get_json", return_value=None):
                with self.assertRaises(RuntimeError):
                    fetch_espn.fetch_season(2026, force=True)
            self.assertEqual(cache.read_text(encoding="utf-8"), "previous-cache")

    def test_refreshed_forecast_respects_actual_finalists(self):
        games = pd.read_csv(ROOT / "data/all_games.csv", parse_dates=["date"])
        seeds = S.playoff_seeds(games)
        self.assertEqual(seeds[4:6], ["Washington Mystics", "Indiana Fever"])
        observed = S.completed_series(games, seeds)
        # Only the Finals are unplayed; hypothetical games are deliberately absent.
        probabilities = {
            ("Golden State Valkyries", "Atlanta Dream", True): .6,
            ("Golden State Valkyries", "Atlanta Dream", False): .4,
        }
        for _ in range(100):
            f1, f2, champion = S.sim_bracket(seeds, probabilities, np.random.default_rng(), observed)
            self.assertEqual({f1, f2}, {"Golden State Valkyries", "Atlanta Dream"})
            self.assertIn(champion, {f1, f2})


if __name__ == "__main__":
    unittest.main()
