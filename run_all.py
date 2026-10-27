"""
run_all.py
==========
End-to-end pipeline for the 2026 WNBA Finals prediction. Runs every stage in the
order the methodology requires:

    1. fetch      -> download / refresh game logs (2016-2026) from ESPN
    2. features   -> build the leakage-free matchup table
    3. model      -> train + time-validate logistic & gradient-boosting models
    4. simulate   -> Monte-Carlo the real 3-round bracket 20,000 times
    5. visuals    -> Finals-probability bar chart
    6. explain    -> SHAP global + local explanations
    7. compare    -> model vs. live sportsbook odds

Run:  python run_all.py            (uses cached seasons; refreshes 2026)
      python run_all.py --refresh  (force re-download every season)
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")  # quiet sklearn/shap chatter for a clean log
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fetch_espn import fetch_all
import model as model_mod
import simulate as sim_mod
import visuals as vis_mod
import explain as explain_mod
import compare_odds as odds_mod

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "outputs")


def make_refresh_meta(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with open(os.path.join(ROOT, "refresh_schedule.json"), encoding="utf-8") as f:
        schedule = json.load(f)
    local_now = now.astimezone(ZoneInfo(schedule["timezone"]))
    next_run = local_now.replace(hour=schedule["hour"], minute=schedule["minute"],
                                 second=0, microsecond=0)
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return {
        "last_updated": now.isoformat().replace("+00:00", "Z"),
        "next_refresh_at": next_run.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schedule_label": schedule["label"],
        "schedule_timezone": schedule["timezone"],
        "scheduler": schedule.get("scheduler", "local"),
    }


def write_refresh_meta(meta: dict) -> None:
    for folder in ("public", "site"):
        target = os.path.join(ROOT, folder, "refresh_meta.json")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target + ".tmp", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
            f.write("\n")
        os.replace(target + ".tmp", target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="force re-download of all historical seasons")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--skip-fetch", action="store_true",
                    help="rebuild predictions from the already refreshed local game cache")
    args = ap.parse_args()

    print("\n[1/7] Fetching game logs ...")
    if not args.skip_fetch:
        fetch_all(refresh_current=True) if not args.refresh else fetch_all(
            start=2016, end=2026, refresh_current=True)

    print("\n[2/7] + [3/7] Building features & training / validating models ...")
    model_mod.main()

    print(f"\n[4/7] Simulating the bracket ({args.sims:,} runs) ...")
    res, top_matchups, seeds, feats = sim_mod.run(n_sims=args.sims)
    sim_mod._print_report(res, top_matchups, args.sims)

    print("\n[5/7] Building the Finals-probability chart ...")
    vis_mod.finals_bar(os.path.join(OUT, "finals_probabilities.csv"),
                       os.path.join(OUT, "finals_probabilities.png"))

    print("\n[6/7] Generating SHAP explanations ...")
    explain_mod.main()

    print("\n[7/7] Comparing against sportsbook odds ...")
    odds_mod.compare(os.path.join(OUT, "model_vs_market.png"))

    meta = make_refresh_meta()
    print("\nRebuilding the website ...")
    runpy.run_path(os.path.join(ROOT, "src", "build_site.py"), run_name="__main__",
                   init_globals={"REFRESH_META": meta})
    # Publish the refresh marker last so open tabs only reload a completed build.
    write_refresh_meta(meta)
    print("\nDone. Predictions and website refreshed.")


if __name__ == "__main__":
    main()
