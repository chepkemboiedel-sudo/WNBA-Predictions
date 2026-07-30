"""
explain.py
==========
Use SHAP to open up the per-game logistic model:

  * GLOBAL summary  -> which features matter most across all games, and in which
    direction, ranked by average impact on the predicted win probability.
  * LOCAL waterfalls -> for a couple of concrete 2026 playoff-style matchups,
    show exactly how each feature pushed the prediction up or down.

SHAP explains a linear model cleanly and exactly (no sampling noise): each
feature's contribution is simply its standardized value times its coefficient.
That makes the picture here a faithful, plain-language read of the model.
"""

from __future__ import annotations

import os

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap

from features import FEATURE_COLS, build_matchup_table
from simulate import compute_standings, current_team_features, _feature_row

HERE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))
OUT = os.path.abspath(os.path.join(HERE, "..", "outputs"))

# Friendlier axis labels for the plots.
PRETTY = {
    "d_win_pct": "Win% edge",
    "d_pt_diff": "Point-diff edge",
    "d_pt_diff_l10": "Recent-form edge (L10)",
    "d_pyth": "Pythagorean edge",
    "d_venue_wp": "Home/away-split edge",
    "d_sos": "Strength-of-schedule edge",
    "d_rest": "Rest-days edge",
    "home": "Home court",
}


def _split_pipeline(model):
    """Pull the scaler and logistic step out of the fitted pipeline."""
    return model.named_steps["scale"], model.named_steps["lr"]


def global_summary(model, background: pd.DataFrame, path: str):
    """SHAP beeswarm summary over a representative sample of games."""
    scaler, lr = _split_pipeline(model)
    Xs = scaler.transform(background[FEATURE_COLS])
    explainer = shap.LinearExplainer(lr, Xs, feature_names=[PRETTY[c] for c in FEATURE_COLS])
    sv = explainer(Xs)

    plt.figure()
    shap.summary_plot(sv, features=Xs, feature_names=[PRETTY[c] for c in FEATURE_COLS], show=False)
    plt.title("SHAP: what drives the win-probability model")
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"SHAP global summary -> {path}")


def local_matchup(model, feats, team_a: str, team_b: str, a_home: bool, path: str):
    """SHAP waterfall for a single 'team_a (home) vs team_b' game."""
    scaler, lr = _split_pipeline(model)
    row = pd.DataFrame([_feature_row(feats[team_a], feats[team_b], a_home)], columns=FEATURE_COLS)
    Xs = scaler.transform(row)
    explainer = shap.LinearExplainer(lr, scaler.transform(_background(model)),
                                     feature_names=[PRETTY[c] for c in FEATURE_COLS])
    sv = explainer(Xs)
    p = model.predict_proba(row)[0][1]

    plt.figure()
    shap.plots.waterfall(sv[0], show=False)
    plt.title(f"{team_a} (home) vs {team_b}\nmodel P({team_a} win) = {p:.0%}", fontsize=10)
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"SHAP local ({team_a} vs {team_b}) -> {path}   P={p:.1%}")


# Cache the background matrix so we build it once.
_BG = None
def _background(model):
    global _BG
    if _BG is None:
        games = pd.read_csv(os.path.join(DATA, "all_games.csv"), parse_dates=["date"])
        m = build_matchup_table(games)
        _BG = m[m.season <= 2025][FEATURE_COLS].sample(500, random_state=1).reset_index(drop=True)
    return _BG


def main():
    os.makedirs(OUT, exist_ok=True)
    bundle = joblib.load(os.path.join(DATA, "models.joblib"))
    model = bundle["logistic"]

    games = pd.read_csv(os.path.join(DATA, "all_games.csv"), parse_dates=["date"])

    # Global summary over a sample of historical + current matchups.
    global_summary(model, _background(model), os.path.join(OUT, "shap_summary.png"))

    # Local explanations for high-profile potential 2026 playoff games.
    seeds = compute_standings(games)["team"].head(8).tolist()
    feats = current_team_features(games, seeds)
    # 1) The #1 seed hosting the #2 seed -- a marquee title-contender clash.
    local_matchup(model, feats, "Minnesota Lynx", "Las Vegas Aces", True,
                  os.path.join(OUT, "shap_local_MIN_vs_LV.png"))
    # 2) A potential semifinal: Minnesota hosting the team that most often
    #    upsets it out of the top bracket half.
    local_matchup(model, feats, "Minnesota Lynx", "Indiana Fever", True,
                  os.path.join(OUT, "shap_local_MIN_vs_IND.png"))
    # 3) The two strongest bottom-half seeds.
    local_matchup(model, feats, "Las Vegas Aces", "Golden State Valkyries", True,
                  os.path.join(OUT, "shap_local_LV_vs_GSV.png"))


if __name__ == "__main__":
    main()
