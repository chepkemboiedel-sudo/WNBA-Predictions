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
import os
import sys
import warnings

warnings.filterwarnings("ignore")  # quiet sklearn/shap chatter for a clean log
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fetch_espn import fetch_all           # noqa: E402
import model as model_mod                  # noqa: E402
import simulate as sim_mod                 # noqa: E402
import visuals as vis_mod                  # noqa: E402
import explain as explain_mod              # noqa: E402
import compare_odds as odds_mod            # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "outputs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="force re-download of all historical seasons")
    ap.add_argument("--sims", type=int, default=20000)
    args = ap.parse_args()

    print("\n[1/7] Fetching game logs ...")
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

    print("\nDone. All outputs written to ./outputs/")


if __name__ == "__main__":
    main()
