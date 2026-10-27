"""Missing players must change only justified, unplayed game probabilities."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import availability as A
import simulate as S

NOW=datetime(2026,10,27,20,tzinfo=timezone.utc)
NEXT={"date":"2026-10-29T16:30:00Z"}


class AvailabilityTests(TestCase):
    def test_season_long_absence_and_later_return(self):
        report={"status":"Out","date":"2026-09-17T16:08Z","details":{"fantasyStatus":{"abbreviation":"OFS"}}}
        self.assertEqual(A.evaluate_report(report,now=NOW,last_played="2026-08-13T20:00Z")["scope"],"long_term")
        self.assertEqual(A.evaluate_report(report,now=NOW,last_played="2026-10-20T20:00Z")["scope"],"none")

    def test_old_or_uncertain_reports_do_not_invent_absences(self):
        old={"status":"Out","date":"2026-09-23T22:50Z","details":{"returnDate":"2027-05-01"}}
        self.assertEqual(A.evaluate_report(old,now=NOW,next_game=NEXT)["scope"],"none")
        questionable={"status":"Questionable","date":"2026-10-27T12:00Z"}
        self.assertEqual(A.evaluate_report(questionable,now=NOW,next_game=NEXT)["scope"],"none")

    def test_recent_out_status_is_next_game_only(self):
        report={"status":"Out","date":"2026-10-27T12:00Z","details":{"returnDate":"2026-11-01"}}
        self.assertEqual(A.evaluate_report(report,now=NOW,next_game=NEXT)["scope"],"next_game")
        report["details"]["returnDate"]="2026-10-29"
        self.assertEqual(A.evaluate_report(report,now=NOW,next_game=NEXT)["scope"],"none")

    def test_long_absences_are_not_counted_twice(self):
        self.assertEqual(A.absence_penalty(4,0),0)
        self.assertAlmostEqual(A.absence_penalty(4,.2),.8)
        team={"players":[{"scope":"long_term","extra_absence_points":4},{"scope":"long_term","extra_absence_points":4}]}
        self.assertEqual(A.team_shift(team),-6)
        team["adjustment_ready"]=False
        self.assertEqual(A.team_shift(team),0)

    def test_own_absence_lowers_probability_and_preserves_complements(self):
        p=A.adjust_probability(.6,-2,0,.1)
        self.assertLess(p,.6)
        self.assertAlmostEqual(p+A.adjust_probability(.4,0,-2,.1),1)

    def test_next_game_report_does_not_persist_to_game_seven(self):
        class FixedRandom:
            calls=0
            def random(self):
                self.calls+=1
                return .5
        rng=FixedRandom()
        probabilities={("A","B",True):1,("A","B",False):1,("A","B",False,"next"):0}
        winner=S.sim_series("A","B","FINALS",probabilities,rng,{"A|B":{"hw":3,"lw":2}})
        self.assertEqual(winner,"A")
        self.assertEqual(rng.calls,2)

    def test_boxscore_minutes_override_unreliable_active_flag(self):
        game=SimpleNamespace(game_id=1,season=2026,date="2026-10-27",is_playoff=True,home_team="A",away_team="B")
        payload={"header":{"id":"1","season":{"year":2026},"competitions":[{"date":"2026-10-27T20:00Z","status":{"type":{"completed":True}}}]},"boxscore":{"players":[]}}
        for team in ("A","B"):
            entries=[{"athlete":{"id":team+str(i),"displayName":team+str(i)},"active":False,"didNotPlay":False,"stats":["40","10"]} for i in range(5)]
            payload["boxscore"]["players"].append({"team":{"displayName":team},"statistics":[{"labels":["MIN","PTS"],"athletes":entries}]})
        rows=A.parse_boxscore(payload,game)
        self.assertEqual(sum(row["minutes"] for row in rows),400)

    def test_stale_feed_disables_adjustments(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,"player_availability.json").write_text(json.dumps({"fetched_at":"2026-10-25T00:00Z","apply_adjustments":True,"teams":{}}))
            with patch.object(A,"DATA",Path(directory)):
                report=A.load_snapshot(now=NOW)
            self.assertFalse(report["apply_adjustments"])
            self.assertEqual(report["status"],"stale")

    def test_matrix_uses_missing_player_effect(self):
        class CoinModel:
            def predict_proba(self,rows):
                return np.array([[.5,.5]]*len(rows))
        form={"win_pct":.5,"pt_diff":0,"pt_diff_l10":0,"pyth":.5,"venue_home_wp":.5,"venue_away_wp":.5,"sos":.5}
        report={"apply_adjustments":True,"model":{"margin_logit_coefficient":.1},"teams":{"A":{"players":[{"scope":"long_term","extra_absence_points":2}]}}}
        matrix=S.build_prob_matrix(CoinModel(),{"A":form,"B":form},["A","B"],report)
        self.assertLess(matrix[("A","B",True)],.5)
        self.assertAlmostEqual(matrix[("A","B",True)]+matrix[("B","A",False)],1)
