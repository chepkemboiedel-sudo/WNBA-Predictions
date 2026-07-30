"""
features.py
===========
Turn the raw event-level game log (one row per game) into two things:

    1. A LONG per-team-per-game table where every row describes one team's form
       *as of the moment just before that game* -- no information from the game
       itself or any later game leaks in.

    2. A MATCHUP table the model actually trains on: one row per team-orientation
       of each game, holding the DIFFERENCE between the two teams' features plus
       a home-court indicator, and a 0/1 target for whether that team won.

The golden rule throughout: a feature attached to a game may only use data from
*earlier* games. We enforce that with pandas' expanding()/rolling() followed by
.shift(1), which drops the current game out of every running statistic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Pythagorean win-expectation exponent. Daryl Morey's basketball-specific value
# of 13.91 is the classic figure from the sports-analytics literature (the
# baseball original uses 2; basketball needs a much larger exponent because
# scoring margins are proportionally smaller). Kept as a constant so it is easy
# to swap for e.g. Hollinger's 16.5 and re-test.
PYTH_EXP = 13.91

# Feature columns the model consumes (all are team-minus-opponent differences,
# except `home`). Defined once so training and simulation stay in lock-step.
FEATURE_COLS = [
    "d_win_pct",     # season win% edge
    "d_pt_diff",     # season average point-differential edge
    "d_pt_diff_l10", # recent-form edge (last 10 games' margin)
    "d_pyth",        # Pythagorean expected-win% edge
    "d_venue_wp",    # edge in win% at the venue type each team is playing in
    "d_sos",         # strength-of-schedule edge (opponents faced so far)
    "d_rest",        # rest-days edge (fatigue)
    "home",          # +1 if this team is at home, -1 away, 0 neutral court
]


# --------------------------------------------------------------------------- #
# Step 1: explode each game into two team-perspective rows
# --------------------------------------------------------------------------- #
def _to_long(games: pd.DataFrame) -> pd.DataFrame:
    """One game -> two rows: the home team's view and the away team's view."""
    home = pd.DataFrame(
        {
            "game_id": games["game_id"],
            "date": games["date"],
            "season": games["season"],
            "is_playoff": games["is_playoff"],
            "team": games["home_team"],
            "opp": games["away_team"],
            "is_home": 1,
            "pts_for": games["home_score"],
            "pts_against": games["away_score"],
            "won": games["home_win"],
        }
    )
    away = pd.DataFrame(
        {
            "game_id": games["game_id"],
            "date": games["date"],
            "season": games["season"],
            "is_playoff": games["is_playoff"],
            "team": games["away_team"],
            "opp": games["home_team"],
            "is_home": 0,
            "pts_for": games["away_score"],
            "pts_against": games["home_score"],
            "won": 1 - games["home_win"],
        }
    )
    long = pd.concat([home, away], ignore_index=True)
    return long.sort_values(["season", "team", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Step 2: attach "as-of" form features to every team-game row
# --------------------------------------------------------------------------- #
def add_team_game_features(games: pd.DataFrame) -> pd.DataFrame:
    """
    Build the long table and attach leakage-free running features per team,
    reset every season. Uses only regular-season games to *build* form (playoff
    rows still get features, computed from that season's prior games).
    """
    long = _to_long(games)
    long["margin"] = long["pts_for"] - long["pts_against"]

    # Group once; every feature is computed within one team's single season.
    grp = long.groupby(["season", "team"], sort=False)

    # --- Win percentage to date -------------------------------------------- #
    # expanding().mean() over the win flag = cumulative win%, then shift(1) so
    # the current game is excluded.
    long["win_pct"] = grp["won"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    long["games_played"] = grp.cumcount()  # number of prior games this season

    # --- Point differential: season average and rolling last-10 ------------ #
    long["d_ptdiff_season"] = grp["margin"].transform(
        lambda s: s.expanding().mean().shift(1)
    )
    long["d_ptdiff_l10"] = grp["margin"].transform(
        lambda s: s.rolling(10, min_periods=3).mean().shift(1)
    )

    # --- Pythagorean win expectation --------------------------------------- #
    # Cumulative points for / against (shifted), then PF^k / (PF^k + PA^k).
    pf = grp["pts_for"].transform(lambda s: s.expanding().sum().shift(1))
    pa = grp["pts_against"].transform(lambda s: s.expanding().sum().shift(1))
    long["pyth"] = pf**PYTH_EXP / (pf**PYTH_EXP + pa**PYTH_EXP)

    # --- Home / away split -------------------------------------------------- #
    # Win% restricted to the venue type of THIS game, computed from prior games
    # of the same type. Captures teams that are notably better at home.
    venue = long.groupby(["season", "team", "is_home"], sort=False)["won"]
    long["venue_wp"] = venue.transform(lambda s: s.expanding().mean().shift(1))

    # --- Rest days / back-to-back ------------------------------------------ #
    long["rest_days"] = grp["date"].transform(lambda s: s.diff().dt.days)
    long["is_b2b"] = (long["rest_days"] <= 1).astype("float")

    # --- Strength of schedule ---------------------------------------------- #
    # For each game we look up the opponent's *own* as-of win% (already computed
    # above, in the opponent's mirrored row for the same game_id). SOS is then
    # the running average of those opponent win%s over games played so far.
    opp_wp = long[["game_id", "team", "win_pct"]].rename(
        columns={"team": "opp", "win_pct": "opp_win_pct"}
    )
    long = long.merge(opp_wp, on=["game_id", "opp"], how="left")
    long = long.sort_values(["season", "team", "date"]).reset_index(drop=True)
    long["sos"] = long.groupby(["season", "team"], sort=False)[
        "opp_win_pct"
    ].transform(lambda s: s.expanding().mean().shift(1))

    return long


# --------------------------------------------------------------------------- #
# Step 3: build the matchup training table (feature DIFFERENCES + target)
# --------------------------------------------------------------------------- #
def build_matchup_table(games: pd.DataFrame, min_prior_games: int = 3) -> pd.DataFrame:
    """
    Produce one row per team-orientation of each game with team-minus-opponent
    feature differences. Because every game yields both orientations (home team's
    view AND away team's view), the resulting model is naturally antisymmetric:
    P(A beats B) and P(B beats A) sum to ~1.

    Rows are dropped when either side has played fewer than `min_prior_games`
    that season, since their running features are too noisy to be meaningful.
    """
    long = add_team_game_features(games)

    # Self-join on game_id to place each team next to its opponent, so we can
    # difference their features. Suffix _t = this team, _o = opponent.
    cols = [
        "game_id", "date", "season", "is_playoff", "team", "is_home", "won",
        "win_pct", "d_ptdiff_season", "d_ptdiff_l10", "pyth", "venue_wp",
        "sos", "rest_days", "games_played",
    ]
    a = long[cols].add_suffix("_t")
    b = long[cols].add_suffix("_o")
    m = a.merge(
        b,
        left_on="game_id_t",
        right_on="game_id_o",
    )
    # Keep only the two genuine orientations (drop self-matches where team==team).
    m = m[m["team_t"] != m["team_o"]].copy()

    # --- Feature differences (this team minus opponent) -------------------- #
    m["d_win_pct"] = m["win_pct_t"] - m["win_pct_o"]
    m["d_pt_diff"] = m["d_ptdiff_season_t"] - m["d_ptdiff_season_o"]
    m["d_pt_diff_l10"] = m["d_ptdiff_l10_t"] - m["d_ptdiff_l10_o"]
    m["d_pyth"] = m["pyth_t"] - m["pyth_o"]
    m["d_venue_wp"] = m["venue_wp_t"] - m["venue_wp_o"]
    m["d_sos"] = m["sos_t"] - m["sos_o"]
    m["d_rest"] = m["rest_days_t"] - m["rest_days_o"]
    # Home indicator from this team's perspective: +1 home, -1 away.
    m["home"] = np.where(m["is_home_t"] == 1, 1.0, -1.0)

    m["target"] = m["won_t"].astype(int)

    # Require enough history on BOTH sides for stable features.
    enough = (m["games_played_t"] >= min_prior_games) & (
        m["games_played_o"] >= min_prior_games
    )
    m = m[enough].copy()

    keep = (
        ["game_id_t", "date_t", "season_t", "is_playoff_t", "team_t", "team_o"]
        + FEATURE_COLS
        + ["target"]
    )
    out = m[keep].rename(
        columns={
            "game_id_t": "game_id",
            "date_t": "date",
            "season_t": "season",
            "is_playoff_t": "is_playoff",
            "team_t": "team",
            "team_o": "opp",
        }
    )
    # Drop any rows with missing features (e.g. rest_days on a season's 1st game).
    out = out.dropna(subset=FEATURE_COLS).reset_index(drop=True)
    return out


if __name__ == "__main__":
    import os
    here = os.path.dirname(__file__)
    games = pd.read_csv(
        os.path.join(here, "..", "data", "all_games.csv"), parse_dates=["date"]
    )
    table = build_matchup_table(games)
    print(f"Matchup rows: {len(table)}  seasons {table.season.min()}-{table.season.max()}")
    print(f"Playoff rows: {int(table.is_playoff.sum())}")
    print("\nFeature summary:")
    print(table[FEATURE_COLS].describe().round(3).T)
    out = os.path.join(here, "..", "data", "matchups.csv")
    table.to_csv(out, index=False)
    print(f"\nSaved -> {out}")
