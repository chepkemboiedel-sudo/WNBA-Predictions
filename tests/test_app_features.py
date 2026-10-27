"""Regression checks for published history, team statistics, and failed refreshes."""
import json
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from app_data import append_snapshot, failed_health, snapshot, team_profiles


class AppFeaturesTests(TestCase):
    def test_history_preserves_archives_and_deduplicates_rebuilds(self):
        table = pd.DataFrame([{"seed":1,"team":"Team A","p_reach_finals":.7,"p_champion":.3}])
        archived = snapshot(table, {"data_through":"2026-07-30","n_sims":20000}, {}, source="archived project output")
        current = snapshot(table, {"data_through":"2026-10-27","n_sims":20000}, {"last_updated":"2026-10-27T19:25:00Z"})
        history = append_snapshot({"version":1,"snapshots":[archived]}, current)
        rebuilt = append_snapshot(history, current)
        self.assertEqual(len(rebuilt["snapshots"]), 2)
        self.assertIsNone(rebuilt["snapshots"][0]["generated_at"])
        self.assertEqual(rebuilt["snapshots"][0]["teams"][0]["champion"], .3)
        self.assertEqual(len(history["snapshots"]), 2)

    def test_failed_attempt_keeps_last_success_and_coverage(self):
        previous = {"status":"ok","last_success_at":"2026-10-26T14:03:00Z",
                    "data_through":"2026-10-25","coverage":{"season_games":350}}
        report = failed_health(previous, run_url="https://github.com/example/repo/actions/runs/1")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["last_success_at"], previous["last_success_at"])
        self.assertEqual(report["coverage"], previous["coverage"])
        self.assertEqual(previous["status"], "ok")

    def test_team_statistics_keep_playoffs_separate(self):
        games = pd.DataFrame([
            {"game_id":1,"date":"2026-05-01","season":2026,"is_playoff":False,"home_team":"A","away_team":"B","home_score":90,"away_score":80,"home_win":1},
            {"game_id":2,"date":"2026-05-03","season":2026,"is_playoff":False,"home_team":"B","away_team":"A","home_score":85,"away_score":75,"home_win":1},
            {"game_id":3,"date":"2026-10-01","season":2026,"is_playoff":True,"home_team":"A","away_team":"B","home_score":100,"away_score":70,"home_win":1},
        ])
        results = pd.DataFrame([{"team":"A","p_champion":1,"p_reach_finals":1}])
        a, b = team_profiles(games, results, ["A"])
        self.assertEqual(a["regular"], {"wins":1,"losses":1})
        self.assertEqual(a["playoffs"], {"wins":1,"losses":0})
        self.assertEqual(a["point_diff"], 0)
        self.assertEqual(a["home"], {"wins":1,"losses":0})
        self.assertTrue(a["recent"][0]["playoff"])
        self.assertEqual(a["head_to_head"][0]["wins"], 1)
        self.assertIsNone(b["probabilities"])

    def test_failure_reporting_helpers_do_not_require_installed_dependencies(self):
        code = "import sys; sys.path.insert(0, 'src'); from app_data import failed_health; assert failed_health({})['status']=='failed'"
        result = subprocess.run([sys.executable,"-S","-c",code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failure_reporter_never_rewrites_published_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("src", "scripts", "public", "data"):
                (root / folder).mkdir()
            shutil.copy(ROOT / "src/app_data.py", root / "src/app_data.py")
            shutil.copy(ROOT / "scripts/record_refresh_failure.py", root / "scripts/record_refresh_failure.py")
            old_health = {"status":"ok", "last_success_at":"2026-10-27T14:00:00Z", "data_through":"2026-10-27"}
            (root / "public/refresh_health.json").write_text(json.dumps(old_health))
            (root / "public/index.html").write_text("last successful forecast")
            (root / "data/forecast_history.json").write_text("saved history")
            result = subprocess.run([sys.executable,"-S",str(root / "scripts/record_refresh_failure.py")],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / "public/refresh_health.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["last_success_at"], old_health["last_success_at"])
            self.assertEqual((root / "public/index.html").read_text(), "last successful forecast")
            self.assertEqual((root / "data/forecast_history.json").read_text(), "saved history")
