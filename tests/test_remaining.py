"""Regression checks for evidence gates, source restrictions, and season rollover."""
import copy
import sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import promotion as P
import seasons
import player_context as C
import fetch_espn as F

class RemainingTests(TestCase):
    def rows(self,n=100):
        rows=[]
        for i in range(n):
            tip=datetime(2027,5,1,tzinfo=timezone.utc)+timedelta(days=i)
            rows.append(dict(game_id=str(i),tip=tip.isoformat(),locked_at=(tip-timedelta(hours=2)).isoformat(),
                status='settled',model_version='v2',model_sha256='hash',snapshot={'fetched_at':(tip-timedelta(hours=2,minutes=1)).isoformat()},local_date=tip.date().isoformat(),
                home_win=i%2,p_baseline=.4 if i%2 else .6,p_adjusted=.9 if i%2 else .1))
        return rows

    def test_promotion_requires_frozen_independent_new_version_games(self):
        rows=self.rows()
        self.assertFalse(P.evaluate({'predictions':rows[:99]},'v2',2027)['promoted'])
        result=P.evaluate({'predictions':rows},'v2',2027)
        self.assertTrue(result['promoted'])
        self.assertFalse(P.evaluate({'predictions':rows},'v1',2027)['promoted'])
        self.assertFalse(P.evaluate({'predictions':rows},'v2',2026)['promoted'])
        invalid=copy.deepcopy(rows)
        invalid[0]['locked_at']=invalid[0]['tip']
        self.assertFalse(P.evaluate({'predictions':invalid},'v2',2027)['promoted'])
        self.assertEqual(P.evaluate({'predictions':rows+rows},'v2',2027)['eligible_games'],100)
        pending=copy.deepcopy(rows+self.rows(101)[100:])
        pending[0]['status']='pending'
        held=P.evaluate({'predictions':pending},'v2',2027)
        self.assertEqual(held['checks'],[],'pending first block must keep its reserved slots')

    def test_unchanged_forecasts_and_repeated_checks_cannot_promote(self):
        rows=self.rows()
        for r in rows:r['p_adjusted']=r['p_baseline']
        a=P.evaluate({'predictions':rows},'v2',2027)
        self.assertFalse(a['promoted'])
        self.assertEqual(a,P.evaluate({'predictions':rows},'v2',2027))

    def test_minute_cap_requires_fresh_explicit_non_negated_report(self):
        now=datetime(2027,6,1,12,tzinfo=timezone.utc)
        game={'date':(now+timedelta(hours=5)).isoformat(),'event_id':'123'}
        report={'date':now.isoformat(),'shortComment':'Will have a 20-minute restriction.'}
        self.assertEqual(C.minute_limit(report,now,game,30)['fraction_missing'],.3333)
        for text in ('No 20-minute restriction.','Might have a 20-minute restriction.','Minutes could be limited.','The 20-minute restriction was lifted.'):
            self.assertIsNone(C.minute_limit(dict(report,shortComment=text),now,game,30),text)
        self.assertIsNone(C.minute_limit(report,now+timedelta(days=5),game,30))
        self.assertIsNone(C.minute_limit(report,now,game,30,last_played=(now+timedelta(hours=1)).isoformat()))

    def test_rollover_waits_for_sufficient_new_season_data(self):
        rows=[]
        for year,rounds in ((2026,3),(2027,1)):
            for r in range(rounds):
                for i in range(0,8,2):rows.append(dict(season=year,is_playoff=False,home_team=str(i),away_team=str(i+1)))
        frame=pd.DataFrame(rows)
        self.assertEqual(seasons.forecast_season(frame),2026)
        newer=frame[frame.season==2027]
        ready=pd.concat([frame,newer,newer])
        self.assertEqual(seasons.forecast_season(ready),2027)
        self.assertTrue(seasons.context(ready)['format_provisional'])

    def test_empty_future_season_is_allowed_but_existing_cache_never_erased(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder,patch.object(F,'DATA_DIR',folder),patch.object(F,'_game_dates_for_season',return_value=[]):
            self.assertTrue(F.fetch_season(2027,allow_empty=True).empty)
            cache=Path(folder)/'games_2027.csv';cache.write_text('old')
            with self.assertRaises(RuntimeError):F.fetch_season(2027,force=True,allow_empty=True)
            self.assertEqual(cache.read_text(),'old')

