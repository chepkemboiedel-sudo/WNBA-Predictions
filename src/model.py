"""
model.py
========
Train and validate the per-game win-probability model:  given both teams' form
features, estimate P(this team beats that team).

Design choices explained in plain language:

* We train on the DIFFERENCE features from features.py. Because each game is fed
  in both orientations (team A's view and team B's view), the model learns an
  antisymmetric function: P(A beats B) and P(B beats A) naturally sum to ~1.

* Two models are compared, exactly as the brief asks:
    - Logistic regression -- a simple, interpretable baseline whose coefficients
      tell you how much each feature moves the win probability.
    - Gradient boosting -- a flexible tree model that can capture interactions
      the linear model misses.

* Validation splits by TIME, never randomly: we train on early seasons and test
  on later ones. A random split would let the model peek at the future (games
  from the same season it is being tested on), inflating the scores.

* We report log-loss and Brier score -- both reward well-calibrated PROBABILITIES,
  not just right/wrong calls -- alongside accuracy, and compare against the
  "better regular-season record wins" baseline the brief specifies.
"""

from __future__ import annotations

import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from features import FEATURE_COLS, build_matchup_table

HERE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))
OUT = os.path.abspath(os.path.join(HERE, "..", "outputs"))


# --------------------------------------------------------------------------- #
# Model builders
# --------------------------------------------------------------------------- #
def make_logistic() -> Pipeline:
    """Standardize features, then fit L2-regularized logistic regression."""
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("lr", LogisticRegression(C=1.0, max_iter=1000)),
        ]
    )


def make_gbm() -> GradientBoostingClassifier:
    """A modest gradient-boosted tree ensemble (kept small to avoid overfitting
    on ~a few thousand games)."""
    return GradientBoostingClassifier(
        n_estimators=200,
        max_depth=2,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )


# --------------------------------------------------------------------------- #
# Evaluation helpers
# --------------------------------------------------------------------------- #
def evaluate(name: str, y_true, p_pred) -> dict:
    """Compute the three headline metrics and print a one-line summary."""
    res = {
        "model": name,
        "log_loss": log_loss(y_true, p_pred),
        "brier": brier_score_loss(y_true, p_pred),
        "accuracy": accuracy_score(y_true, (p_pred >= 0.5).astype(int)),
        "n": len(y_true),
    }
    print(
        f"  {name:24}  log-loss={res['log_loss']:.4f}  "
        f"Brier={res['brier']:.4f}  acc={res['accuracy']:.3f}  (n={res['n']})"
    )
    return res


def better_record_baseline(test: pd.DataFrame) -> np.ndarray:
    """
    Baseline (a) from the brief: 'the team with the better record wins.'
    Turned into a probability so it can be scored with log-loss: predict a
    confident-but-not-certain 0.75 for the higher-win% team, 0.25 for the lower,
    and 0.5 on an exact tie. (0.75 is roughly the historical hit rate of the
    better-record team, which keeps the baseline fairly calibrated.)
    """
    d = test["d_win_pct"].to_numpy()
    return np.where(d > 0, 0.75, np.where(d < 0, 0.25, 0.5))


# --------------------------------------------------------------------------- #
# Main training / validation routine
# --------------------------------------------------------------------------- #
def train_and_validate(
    matchups: pd.DataFrame,
    train_seasons: range,
    test_seasons: range,
):
    """Fit both models on train_seasons, score them on test_seasons."""
    train = matchups[matchups.season.isin(train_seasons)]
    test = matchups[matchups.season.isin(test_seasons)]

    Xtr, ytr = train[FEATURE_COLS], train["target"]
    Xte, yte = test[FEATURE_COLS], test["target"]

    print(
        f"Train: {len(train)} rows ({train.season.min()}-{train.season.max()})  |  "
        f"Test: {len(test)} rows ({test.season.min()}-{test.season.max()})"
    )
    print("\nHeld-out validation metrics (lower log-loss / Brier is better):")

    results = []
    # Baseline first, so we can see whether the models actually beat it.
    results.append(evaluate("baseline: better record", yte, better_record_baseline(test)))

    lr = make_logistic().fit(Xtr, ytr)
    results.append(evaluate("logistic regression", yte, lr.predict_proba(Xte)[:, 1]))

    gbm = make_gbm().fit(Xtr, ytr)
    results.append(evaluate("gradient boosting", yte, gbm.predict_proba(Xte)[:, 1]))

    return lr, gbm, pd.DataFrame(results)


def report_logistic_coefficients(lr: Pipeline):
    """Print the standardized logistic-regression weights -- a plain-language
    read on which features drive the prediction and in which direction."""
    coefs = lr.named_steps["lr"].coef_[0]
    print("\nLogistic-regression coefficients (per 1 SD of each feature):")
    order = np.argsort(-np.abs(coefs))
    for i in order:
        arrow = "favors this team" if coefs[i] > 0 else "favors opponent"
        print(f"  {FEATURE_COLS[i]:14} {coefs[i]:+.3f}  ({arrow})")


def calibration_plot(models: dict, test: pd.DataFrame, path: str):
    """
    Reliability diagram: bucket predictions by predicted probability and plot the
    ACTUAL win rate in each bucket. A well-calibrated model hugs the diagonal
    (when it says 70%, teams really win ~70% of the time).
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect calibration")
    bins = np.linspace(0, 1, 11)
    for name, p in models.items():
        idx = np.digitize(p, bins) - 1
        xs, ys = [], []
        for b in range(10):
            mask = idx == b
            if mask.sum() >= 15:  # ignore near-empty buckets
                xs.append(p[mask].mean())
                ys.append(test["target"].to_numpy()[mask].mean())
        ax.plot(xs, ys, "o-", label=name, alpha=0.8)
    ax.set_xlabel("Predicted win probability")
    ax.set_ylabel("Actual win rate")
    ax.set_title("Calibration on held-out seasons")
    ax.legend()
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"\nCalibration plot -> {path}")


def main():
    os.makedirs(OUT, exist_ok=True)
    games = pd.read_csv(os.path.join(DATA, "all_games.csv"), parse_dates=["date"])
    matchups = build_matchup_table(games)
    from seasons import forecast_season
    season = forecast_season(games)

    # Time-based split: learn from 2016-2023, validate on the two most recent
    # COMPLETED seasons (2024-2025), which include real playoff games.
    lr, gbm, results = train_and_validate(
        matchups, train_seasons=range(2016, season-2), test_seasons=range(season-2, season)
    )
    report_logistic_coefficients(lr)

    test = matchups[matchups.season.isin(range(season-2, season))]
    calibration_plot(
        {
            "logistic": lr.predict_proba(test[FEATURE_COLS])[:, 1],
            "grad boosting": gbm.predict_proba(test[FEATURE_COLS])[:, 1],
        },
        test,
        os.path.join(OUT, "calibration.png"),
    )

    # Refit the chosen model on ALL completed seasons (2016-2025) before handing
    # it to the bracket simulator, so it uses every game available. We keep the
    # logistic model as the primary predictor: it validated competitively, is
    # naturally antisymmetric, and its probabilities are well-calibrated.
    final_train = matchups[matchups.season < season]
    final_lr = make_logistic().fit(final_train[FEATURE_COLS], final_train["target"])
    final_gbm = make_gbm().fit(final_train[FEATURE_COLS], final_train["target"])
    joblib.dump(
        {"logistic": final_lr, "gbm": final_gbm, "features": FEATURE_COLS},
        os.path.join(DATA, "models.joblib"),
    )
    results.to_csv(os.path.join(OUT, "validation_metrics.csv"), index=False)
    print(f"\nSaved fitted models -> {os.path.join(DATA, 'models.joblib')}")


if __name__ == "__main__":
    main()

