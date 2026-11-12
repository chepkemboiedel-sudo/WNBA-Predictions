"""Time and coverage safeguards for the historical injury comparison."""
import sys
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from zoneinfo import ZoneInfo

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import backtest_availability as B


class BacktestAvailabilityTests(TestCase):
    def test_official_and_espn_team_abbreviations_match(self):
        self.assertEqual(B.matchup_code("POR","LV"),"LVA@PDX")
        self.assertEqual(B.matchup_code("NY","GS"),"GSV@NYL")

    def test_fixed_report_cutoff_rejects_post_tip_information(self):
        tip=datetime(2026,6,16,19,tzinfo=ZoneInfo("America/New_York"))
        selected="2026-06-16T15:00:00-04:00"
        report={"published_at":selected,"players":[]}
        self.assertEqual(B.report_for(tip,{selected:report}),report)
        report["published_at"]="2026-06-16T18:30:00-04:00"
        with self.assertRaises(AssertionError):
            B.report_for(tip,{selected:report})
        self.assertIsNone(B.report_for(tip,{"2026-06-16T18:00:00-04:00":report}))

    def test_report_day_uses_eastern_calendar_not_utc(self):
        tip=datetime.fromisoformat("2026-06-17T02:00:00+00:00")
        report={"published_at":"2026-06-16T15:00:00-04:00"}
        self.assertEqual(B.report_for(tip,{report["published_at"]:report}),report)

    def test_future_outcomes_and_participation_cannot_enter_history(self):
        games=pd.DataFrame({"date":pd.to_datetime(["2026-06-01","2026-07-01","2026-07-02"]),"home_win":[1,0,0]})
        boxes=pd.DataFrame({"date":games.date,"minutes":[30,0,0]})
        before=B.history_before(games,boxes,"2026-07-01")
        games.loc[1:,"home_win"]=1
        boxes.loc[1:,"minutes"]=40
        after=B.history_before(games,boxes,"2026-07-01")
        pd.testing.assert_frame_equal(before[0],after[0])
        pd.testing.assert_frame_equal(before[1],after[1])
        self.assertEqual(len(before[0]),1)

    def test_penalty_uses_prior_participation_and_unique_names_only(self):
        games=pd.DataFrame([{"game_id":str(i),"season":2026,"is_playoff":False,"home_team":"A","away_team":"B"} for i in range(4)])
        boxes=pd.DataFrame([{"game_id":str(i),"season":2026,"is_playoff":False,"team":"A","player_id":"7","player":"Jane Doe","minutes":30 if i<2 else 0} for i in range(4)])
        report={"players":[{"date":"2026-07-01","matchup":"B@A","team":"A","player":"Doe,Jane","status":"Out"}]}
        context={"local_date":"2026-07-01","matchup":"B@A"}
        amount,details,complete=B.team_penalty("A",report,context,games,boxes,{"7":2})
        self.assertTrue(complete)
        self.assertEqual(amount,-1)
        duplicate=boxes.iloc[[0]].copy()
        duplicate["player_id"]="8"
        amount,details,_=B.team_penalty("A",report,context,games,pd.concat([boxes,duplicate]),{"7":2})
        self.assertEqual(amount,0)
        self.assertIsNone(details[0]["id"])
        amount,_,complete=B.team_penalty("A",report,context,games,boxes.iloc[:3],{"7":2})
        self.assertFalse(complete)
        self.assertEqual(amount,0)
        report["players"][0]["status"]="Questionable"
        amount,details,_=B.team_penalty("A",report,context,games,boxes,{"7":2})
        self.assertEqual(amount,0)
        self.assertEqual(details,[])

    def test_single_corrected_pick_is_not_statistical_evidence(self):
        rows=pd.DataFrame({"local_date":["2026-07-01","2026-07-02"],"home_win":[0,1],"p_baseline":[.52,.7],"p_adjusted":[.49,.7]})
        result=B.score(rows,bootstrap=100)
        self.assertEqual(result["n"],2)
        self.assertEqual(result["winner_changes"],{"corrected":1,"harmed":0,"mcnemar_exact_p":1.0})
