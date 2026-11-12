"""Display and export the saved evaluation, not current forecast probabilities."""
import sys
import json
from pathlib import Path
from unittest import TestCase

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import backtest_ui as B


def initial_fixture():
    data=json.loads((ROOT/'data/backtests/initial_results.json').read_text())
    data['date_range']={'from':'2026-05-15','through':'2026-10-26'}
    for key in ('initial_study','newly_evaluated','prospective'):
        data['groups'][key]={'n':0}
    return data


class BacktestUITests(TestCase):
    def test_panel_uses_saved_paired_metrics_and_coverage(self):
        data=initial_fixture()
        panel=B.section(data)
        self.assertIn('id="backtest"',panel)
        self.assertIn('0.556734',panel)
        self.assertIn('0.555921',panel)
        self.assertIn('72.28%',panel)
        self.assertIn('202 of 324',panel)
        self.assertIn('Only 5 covered games were playoff games',panel)
        self.assertIn('Past predictions are retained',panel)
        self.assertIn('Prospective trial',panel)
        self.assertIn('Accuracy difference over time',panel)
        self.assertIn('/backtest/predictions.csv',panel)
        self.assertEqual(data['date_range']['from'],'2026-05-15')
        self.assertEqual(data['date_range']['through'],'2026-10-26')

    def test_accuracy_intervals_are_percentage_points(self):
        group=initial_fixture()['groups']['verified_report_games']
        rows=B.metric_rows(group)
        self.assertIn('-1.48 to +1.46 pp',rows)
        self.assertIn('-0.003812 to +0.002450',rows)
        self.assertIn('+0.00 pp',rows)
