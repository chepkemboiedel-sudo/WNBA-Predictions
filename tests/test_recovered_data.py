"""Recovery must preserve identities, complete totals, and the frozen study."""
import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
import recovered_data as R
import collect_historical_injuries as C

class RecoveredDataTests(TestCase):
    def setUp(self):
        self.evidence=json.loads((ROOT/"data/recovery/boxscore_401856947.json").read_text(encoding="utf-8"))
        self.game=SimpleNamespace(game_id="401856947",season=2026,date="2026-05-29",is_playoff=False,
                                  home_team="Chicago Sky",away_team="Minnesota Lynx",home_score=58,away_score=79)

    def test_recovered_boxscore_matches_both_providers_and_full_game_totals(self):
        rows,identities=R.validate_boxscore(self.evidence,self.game)
        self.assertEqual(len(rows),27)
        self.assertEqual(len({r["player_id"] for r in rows}),27)
        for team,score in (("Chicago Sky",58),("Minnesota Lynx",79)):
            side=[r for r in rows if r["team"]==team]
            self.assertAlmostEqual(sum(r["minutes"] for r in side),200,delta=.1)
            self.assertEqual(sum(r["points"] for r in side),score)
        nia=next(r for r in identities if r["espn_id"]=="3054590")
        self.assertEqual(nia["event_surname"],"Coffey")
        self.assertEqual(nia["wnba_name"],"Nia Coffey")

    def test_bad_identity_or_scores_cannot_be_imported(self):
        for field,value in (("game_id","wrong"),("home_score",59),("season",2025),("date","2026-05-30")):
            game=copy.deepcopy(self.game);setattr(game,field,value)
            with self.assertRaises(ValueError,msg=field):R.validate_boxscore(self.evidence,game)

    def test_missing_or_conflicting_player_statistics_cannot_be_imported(self):
        data=copy.deepcopy(self.evidence);data["espn"]["teams"]["home"]["players"][0]["statistics"]["points"]+=1
        with self.assertRaises(ValueError):R.validate_boxscore(data,self.game)
        data=copy.deepcopy(self.evidence);data["espn"]["teams"]["home"]["players"].pop()
        with self.assertRaises(ValueError):R.validate_boxscore(data,self.game)
        data=copy.deepcopy(self.evidence);data["wnba"]["homeTeam"]["players"][0]["statistics"]["minutes"]="2:50"
        with self.assertRaises(ValueError):R.validate_boxscore(data,self.game)

    def test_mixed_report_keeps_wnba_rows_and_excludes_only_known_nba_placeholders(self):
        known={"AtlantaDream":"ATL","LasVegasAces":"LVA"}
        team={"team":"AtlantaDream","date":"2026-07-04","matchup":"ATL@LVA","submitted":True}
        nba={"team":"AtlantaHawks","date":"2026-07-04","matchup":"ATL@UTA","submitted":False}
        player={"team":"AtlantaDream","player":"Jones,Brionna","status":"Out"}
        accepted,players,excluded=C.wnba_sections([team,nba],[player],known)
        self.assertEqual(accepted,[team]);self.assertEqual(players,[player]);self.assertEqual(excluded,[nba])
        for bad in (dict(nba,team="UnknownClub"),dict(nba,submitted=True),dict(team,matchup="ATL@UTA")):
            with self.assertRaises(ValueError):C.wnba_sections([team,bad],[player],known)
        with self.assertRaises(ValueError):C.wnba_sections([nba],[],known)
        with self.assertRaises(ValueError):C.wnba_sections([team,nba],[dict(player,team="AtlantaHawks")],known)

    def test_archived_pdfs_match_the_validated_report_receipts(self):
        audit=json.loads((ROOT/"data/recovery/audit.json").read_text(encoding="utf-8"))
        self.assertEqual(len(audit["injury_reports"]["recovered"]),5)
        for report in audit["injury_reports"]["recovered"]:
            name=report["url"].rsplit("/",1)[1]
            self.assertEqual(hashlib.sha256((ROOT/"data/recovery/sources"/name).read_bytes()).hexdigest(),report["sha256"])
            parsed=json.loads((ROOT/"data/backtests/injury_reports"/(name[:-4]+".json")).read_text(encoding="utf-8"))
            self.assertEqual(parsed["published_at"],report["published_at"])
            self.assertFalse(any(t["team"] in C.NBA_PLACEHOLDER_TEAMS for t in parsed["teams"]))
            self.assertEqual(len(parsed["excluded_non_wnba_placeholders"]),4)

    def test_frozen_initial_study_is_byte_for_byte_unchanged(self):
        audit=json.loads((ROOT/"data/recovery/audit.json").read_text(encoding="utf-8"))
        for name,expected in audit["protected_backtest_sha256"].items():
            if name.startswith("data/backtests/initial_"):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),expected)

