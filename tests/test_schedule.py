"""Daily scheduling and publication behavior for unattended refreshes."""
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

import run_all


class ScheduleTests(TestCase):
    def test_before_daily_run(self):
        meta = run_all.make_refresh_meta(datetime(2026, 10, 27, 13, tzinfo=timezone.utc))
        self.assertEqual(meta["next_refresh_at"], "2026-10-27T14:00:00Z")

    def test_after_daily_run(self):
        meta = run_all.make_refresh_meta(datetime(2026, 10, 27, 15, tzinfo=timezone.utc))
        self.assertEqual(meta["next_refresh_at"], "2026-10-28T14:00:00Z")

    def test_pacific_daylight_saving_transition(self):
        meta = run_all.make_refresh_meta(datetime(2026, 10, 31, 15, tzinfo=timezone.utc))
        self.assertEqual(meta["next_refresh_at"], "2026-11-01T15:00:00Z")

    def test_failed_build_does_not_publish_success(self):
        with patch("sys.argv", ["run_all.py", "--skip-fetch"]), \
             patch.object(run_all.model_mod, "main"), \
             patch.object(run_all.sim_mod, "run", return_value=(None, None, None, None)), \
             patch.object(run_all.sim_mod, "_print_report"), \
             patch.object(run_all.vis_mod, "finals_bar"), \
             patch.object(run_all.explain_mod, "main"), \
             patch.object(run_all.odds_mod, "compare"), \
             patch.object(run_all.runpy, "run_path", side_effect=RuntimeError("build failed")), \
             patch.object(run_all, "write_refresh_meta") as publish:
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                run_all.main()
            publish.assert_not_called()
