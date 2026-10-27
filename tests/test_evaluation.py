"""Prevent hindsight, duplicate games, and loss of a successful evaluation."""
import copy
import json
import shutil
import sys
import tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import evaluation as E

NOW=datetime(2026,10,27,14,tzinfo=timezone.utc)


def fixture():
    games=pd.DataFrame([{"game_id":"old","date":pd.Timestamp("2026-10-26"),"home_team":"A","away_team":"B","home_win":1,"season":2026,"is_playoff":True}])
    snapshot={"fetched_at":(NOW-timedelta(minutes=2)).isoformat(),"apply_adjustments":True,"model":{},"teams":{},"next_games":{
        "A":{"event_id":"new","home":True,"opponent":"B","date":(NOW+timedelta(hours=5)).isoformat(),"is_playoff":True},
        "B":{"event_id":"new","home":False,"opponent":"A","date":(NOW+timedelta(hours=5)).isoformat(),"is_playoff":True}}}
    return games,snapshot,{"started_at":NOW.isoformat(),"predictions":[]}


class EvaluationTests(TestCase):
    def capture(self,ledger,games,snapshot,now=NOW,clock=None):
        def matrices(model,feats,teams,availability=None):
            return {("A","B",True):.6,**({("A","B",True,"next"):.4} if availability else {})}
        with patch.object(E.S,"current_team_features",return_value={}),patch.object(E.S,"build_prob_matrix",side_effect=matrices):
            return E.capture(ledger,games,snapshot,object(),now,"model-hash",clock)

    def test_pregame_predictions_are_frozen_and_not_backfilled(self):
        games,snapshot,ledger=fixture()
        captured=self.capture(ledger,games,snapshot)
        self.assertEqual(len(captured["predictions"]),1)
        row=captured["predictions"][0]
        self.assertEqual(row["p_baseline"],.6)
        self.assertEqual(row["p_adjusted"],.4)
        self.assertLess(E.A.utc(row["locked_at"]),E.A.utc(row["tip"]))
        repeated=self.capture(captured,games,snapshot)
        self.assertEqual(repeated["predictions"],captured["predictions"])
        late=self.capture(ledger,games,snapshot,NOW+timedelta(hours=6))
        self.assertEqual(late["predictions"],[])

    def test_stale_or_late_computation_does_not_create_prospective_evidence(self):
        games,snapshot,ledger=fixture()
        self.assertEqual(self.capture(ledger,games,snapshot,clock=lambda:NOW+timedelta(hours=5))["predictions"],[])
        snapshot["fetched_at"]=(NOW-timedelta(hours=3)).isoformat()
        self.assertEqual(self.capture(ledger,games,snapshot)["predictions"],[])

    def test_outcomes_settle_once_without_altering_probabilities(self):
        games,snapshot,ledger=fixture()
        captured=self.capture(ledger,games,snapshot)
        completed=pd.DataFrame([{"game_id":"new","home_team":"A","away_team":"B","home_win":0,"is_playoff":True}])
        self.assertEqual(E.settle(captured,completed,NOW)["predictions"][0]["status"],"pending")
        settled=E.settle(captured,completed,NOW+timedelta(hours=8))
        self.assertEqual(settled["predictions"][0]["home_win"],0)
        self.assertEqual(settled["predictions"][0]["p_adjusted"],.4)
        self.assertEqual(len(E.trial_frame(settled)),1)
        self.assertEqual(E.settle(settled,completed,NOW+timedelta(days=1)),settled)
        completed.loc[0,"home_team"]="C"
        self.assertEqual(E.settle(captured,completed,NOW+timedelta(hours=8))["predictions"][0]["status"],"pending")

    def test_no_new_games_does_not_refit_or_rewrite_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            for name in ("results.json","predictions.csv"):
                shutil.copyfile(ROOT/"outputs/availability_backtest"/name,target/name)
            original=(target/"predictions.csv").read_bytes()
            with patch.object(E.B,"make_logistic",side_effect=AssertionError("No new games; must not refit")):
                summary,frame=E.B.run(append_only=True,destination=target)
            self.assertEqual((target/"predictions.csv").read_bytes(),original)
            self.assertEqual(len(frame),summary["groups"]["all_eligible_games"]["n"])

    def test_new_game_is_added_without_repredicting_old_games(self):
        class NewModel:
            def fit(self,*args):
                return self
            def predict_proba(self,rows):
                return np.array([[.45,.55]]*len(rows))
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            shutil.copyfile(ROOT/"outputs/availability_backtest/results.json",target/"results.json")
            original=pd.read_csv(ROOT/"outputs/availability_backtest/predictions.csv",dtype={"game_id":str},float_precision="round_trip")
            retained=original.iloc[:-1].copy()
            retained.to_csv(target/"predictions.csv",index=False)
            with patch.object(E.B,"make_logistic",return_value=NewModel()),patch.object(E.B.A,"fit_effects",return_value=({}, {"training_games":100,"margin_logit_coefficient":.1})),patch.object(E.B,"write_report"):
                summary,frame=E.B.run(append_only=True,destination=target)
            self.assertEqual(len(frame),len(original))
            old=frame.set_index("game_id").loc[retained.game_id]
            np.testing.assert_array_equal(old.p_baseline,retained.p_baseline)
            np.testing.assert_array_equal(old.p_adjusted,retained.p_adjusted)
            self.assertEqual(frame.set_index("game_id").loc[original.game_id.iloc[-1]].p_baseline,.55)
            # Empty CSV cells must not become spurious incomplete-archive warnings.
            self.assertEqual(summary['incomplete_team_history_games'],int((frame.report_covered & frame.fallback_reason.str.contains('Incomplete',case=False,na=False)).sum()))

    def test_failed_promotion_rolls_back_all_metric_files(self):
        with tempfile.TemporaryDirectory() as directory:
            first,second=Path(directory)/"a.json",Path(directory)/"b.csv"
            first.write_bytes(b"old-a");second.write_bytes(b"old-b")
            real_replace=E.os.replace
            calls=[]
            def interrupted(source,target):
                calls.append(target)
                if len(calls)==2:
                    raise OSError("interrupted promotion")
                real_replace(source,target)
            with patch.object(E.os,"replace",side_effect=interrupted):
                with self.assertRaises(OSError):
                    E.publish_files({first:b"new-a",second:b"new-b"})
            self.assertEqual(first.read_bytes(),b"old-a")
            self.assertEqual(second.read_bytes(),b"old-b")

    def test_unchanged_checks_add_no_progress_point(self):
        frame=pd.DataFrame({"game_id":["1"],"home_win":[1],"p_baseline":[.5],"p_adjusted":[.6]})
        empty=frame.iloc[:0]
        summary={"groups":{"primary":{"n":1,"metrics":{key:{"delta":0} for key in ("accuracy","log_loss","brier")}}}}
        first=E.checkpoint({"checkpoints":[]},summary,frame,empty,NOW)
        self.assertEqual(len(first["checkpoints"]),1)
        repeated=E.checkpoint(first,summary,frame,empty,NOW+timedelta(days=1))
        self.assertEqual(repeated,first)
        frame.loc[0,"home_win"]=0
        self.assertEqual(len(E.checkpoint(first,summary,frame,empty,NOW)["checkpoints"]),2)

    def test_failed_update_preserves_last_successful_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/"outputs/availability_backtest"
            output.mkdir(parents=True)
            for name in ("results.json","predictions.csv"):
                shutil.copyfile(ROOT/"outputs/availability_backtest"/name,output/name)
            original=(output/"results.json").read_bytes()
            with patch.object(E,"ROOT",root),patch.object(E.reports,"refresh_manifest",side_effect=RuntimeError("feed unavailable")):
                status=E.update(now=NOW)
            self.assertEqual(status["status"],"failed")
            self.assertEqual((output/"results.json").read_bytes(),original)
            self.assertEqual(json.loads((output/"auto_status.json").read_text())["status"],"failed")

    def test_manifest_cache_survives_fresh_cloud_checkouts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"data/backtests").mkdir(parents=True)
            (root/"data/player_game_stats.csv").write_text("season,started_at\n2026,2026-05-08T23:30Z\n")
            url=E.reports.BASE+"Injury-Report_2026-05-08_03_00PM.pdf"
            cached={"status":200,"parser_version":E.reports.PARSER_VERSION,"url":url,"published_at":"2026-05-08T15:00:00-04:00"}
            extra={**cached,"url":url.replace("05-08","05-09")}
            path=root/"data/backtests/injury_report_manifest.json"
            path.write_text(json.dumps({"reports":[cached,extra]}))
            with patch.object(E.reports,"ROOT",root),patch.object(E.reports,"collect",side_effect=AssertionError("Verified cache should be reused")):
                result=E.reports.refresh_manifest(now=NOW)
            self.assertEqual(len(result["reports"]),2)

    def test_full_daily_pipeline_invokes_automatic_evaluation(self):
        import run_all
        events=[]
        with patch.object(sys,"argv",["run_all.py"]),patch.object(run_all,"fetch_all"),patch.object(run_all.model_mod,"main"),patch.object(run_all.availability_mod,"refresh",side_effect=lambda:events.append("players")),patch.object(run_all.evaluation_mod,"update",side_effect=lambda:events.append("evaluation")),patch.object(run_all.sim_mod,"run",side_effect=lambda **kwargs:(events.append("simulation") or (None,None,None,None))),patch.object(run_all.sim_mod,"_print_report"),patch.object(run_all.vis_mod,"finals_bar"),patch.object(run_all.explain_mod,"main"),patch.object(run_all.odds_mod,"compare"),patch.object(run_all,"make_refresh_meta",return_value={}),patch.object(run_all.runpy,"run_path"),patch.object(run_all,"write_refresh_meta"):
            run_all.main()
        self.assertEqual(events,["players","evaluation","simulation"])

