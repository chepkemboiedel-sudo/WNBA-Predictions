"""
simulate.py
===========
Monte-Carlo the ACTUAL 2026 WNBA playoff bracket and tally how often each of the
eight seeded teams reaches the Finals and wins the title.

The real format (no conference brackets, no reseeding between rounds):
    Round 1   best-of-3 : 1v8, 2v7, 3v6, 4v5
    Semifinals best-of-5: winner(1v8) vs winner(4v5),  winner(2v7) vs winner(3v6)
    Finals    best-of-7 : the two semifinal winners
Home court in every series goes to the higher seed, following the league's
standard game-by-game host patterns.

We simulate every INDIVIDUAL game within each series (not a single coin flip for
the whole series), drawing each game from the validated per-game model. Because
only eight teams are involved, we pre-compute the full table of pairwise
game probabilities once, then run tens of thousands of bracket simulations as
fast dictionary look-ups.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict

import joblib
import numpy as np
import pandas as pd

from features import FEATURE_COLS, PYTH_EXP

HERE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))
OUT = os.path.abspath(os.path.join(HERE, "..", "outputs"))

# Conference is shown for reference only -- it plays NO role in seeding or the
# bracket. Used solely for the brief's secondary "which conference" cut.
CONFERENCE = {
    "Minnesota Lynx": "West", "Las Vegas Aces": "West",
    "Golden State Valkyries": "West", "Dallas Wings": "West",
    "Indiana Fever": "East", "Atlanta Dream": "East",
    "New York Liberty": "East", "Washington Mystics": "East",
}

# Home-court host pattern for each series length. "H" = higher seed hosts,
# "L" = lower seed hosts. Standard WNBA formats:
SERIES_FORMATS = {
    "R1":     list("HLH"),        # best-of-3, higher seed hosts G1 & G3
    "SEMI":   list("HHLLH"),      # best-of-5, 2-2-1
    "FINALS": list("HHLLHLH"),    # best-of-7, 2-2-1-1-1
}


# --------------------------------------------------------------------------- #
# 1. Standings, seeding, and current team form
# --------------------------------------------------------------------------- #
def compute_standings(games: pd.DataFrame, season: int = 2026) -> pd.DataFrame:
    """Regular-season W-L, win%, and season point differential for `season`."""
    reg = games[(games.season == season) & (~games.is_playoff)]
    rec = defaultdict(lambda: {"w": 0, "l": 0, "pf": 0, "pa": 0})
    for _, r in reg.iterrows():
        h, a = r.home_team, r.away_team
        rec[h]["pf"] += r.home_score; rec[h]["pa"] += r.away_score
        rec[a]["pf"] += r.away_score; rec[a]["pa"] += r.home_score
        if r.home_win:
            rec[h]["w"] += 1; rec[a]["l"] += 1
        else:
            rec[a]["w"] += 1; rec[h]["l"] += 1
    rows = []
    for t, d in rec.items():
        g = d["w"] + d["l"]
        rows.append({
            "team": t, "w": d["w"], "l": d["l"],
            "win_pct": d["w"] / g if g else 0,
            "pt_diff": (d["pf"] - d["pa"]) / g if g else 0,
        })
    # Seed by win% then season point differential (a simplified stand-in for the
    # league's full head-to-head tiebreaker chain -- noted as an approximation).
    return (
        pd.DataFrame(rows)
        .sort_values(["win_pct", "pt_diff"], ascending=False)
        .reset_index(drop=True)
    )


def current_team_features(games: pd.DataFrame, teams: list[str], season: int = 2026) -> dict:
    """
    Snapshot each playoff team's form using ALL its regular-season games this
    year (inclusive -- there is no leakage, because the playoffs happen later).
    Returns a dict: team -> feature values consumed by the matchup builder.
    """
    reg = games[(games.season == season) & (~games.is_playoff)]
    # Final regular-season win% per team, used for strength-of-schedule.
    final_wp = {}
    for t in reg.home_team.unique().tolist() + reg.away_team.unique().tolist():
        gm = reg[(reg.home_team == t) | (reg.away_team == t)]
        w = ((gm.home_team == t) & (gm.home_win == 1)).sum() + \
            ((gm.away_team == t) & (gm.home_win == 0)).sum()
        final_wp[t] = w / len(gm) if len(gm) else 0.0

    feats = {}
    for t in teams:
        gm = reg[(reg.home_team == t) | (reg.away_team == t)].sort_values("date")
        pf, pa, margins, opps, home_res, away_res = [], [], [], [], [], []
        for _, r in gm.iterrows():
            is_home = r.home_team == t
            tf = r.home_score if is_home else r.away_score
            ta = r.away_score if is_home else r.home_score
            pf.append(tf); pa.append(ta); margins.append(tf - ta)
            opps.append(r.away_team if is_home else r.home_team)
            won = int((is_home and r.home_win) or (not is_home and not r.home_win))
            (home_res if is_home else away_res).append(won)
        PF, PA = sum(pf), sum(pa)
        feats[t] = {
            "win_pct": final_wp[t],
            "pt_diff": float(np.mean(margins)),
            "pt_diff_l10": float(np.mean(margins[-10:])),
            "pyth": PF**PYTH_EXP / (PF**PYTH_EXP + PA**PYTH_EXP),
            "venue_home_wp": float(np.mean(home_res)) if home_res else 0.5,
            "venue_away_wp": float(np.mean(away_res)) if away_res else 0.5,
            "sos": float(np.mean([final_wp.get(o, 0.5) for o in opps])),
        }
    return feats


# --------------------------------------------------------------------------- #
# 2. Per-game probability from the model (antisymmetric)
# --------------------------------------------------------------------------- #
def _feature_row(A: dict, B: dict, a_home: bool) -> list[float]:
    """Build the model's feature vector for 'team A vs team B', A's perspective."""
    return [
        A["win_pct"] - B["win_pct"],                                    # d_win_pct
        A["pt_diff"] - B["pt_diff"],                                    # d_pt_diff
        A["pt_diff_l10"] - B["pt_diff_l10"],                            # d_pt_diff_l10
        A["pyth"] - B["pyth"],                                          # d_pyth
        (A["venue_home_wp"] if a_home else A["venue_away_wp"])          # d_venue_wp
        - (B["venue_away_wp"] if a_home else B["venue_home_wp"]),
        A["sos"] - B["sos"],                                            # d_sos
        0.0,                                                            # d_rest (neutral in playoffs)
        1.0 if a_home else -1.0,                                        # home
    ]


def prob_A_beats_B(model, A: dict, B: dict, a_home: bool) -> float:
    """
    P(A beats B) with A at home (a_home=True) or away. Averaged over both team
    orientations so the estimate is exactly antisymmetric even for a tree model.
    """
    # Wrap in a named DataFrame so column names match how the model was fit.
    rows = pd.DataFrame(
        [_feature_row(A, B, a_home), _feature_row(B, A, not a_home)],
        columns=FEATURE_COLS,
    )
    p_a, p_b = model.predict_proba(rows)[:, 1]  # P(A beats B), P(B beats A)
    return 0.5 * (p_a + (1.0 - p_b))


def build_prob_matrix(model, feats: dict, teams: list[str]) -> dict:
    """Pre-compute P(x beats y | x at home) for every ordered pair -- 8x8x(home)."""
    P = {}
    for x in teams:
        for y in teams:
            if x == y:
                continue
            P[(x, y, True)] = prob_A_beats_B(model, feats[x], feats[y], a_home=True)
            P[(x, y, False)] = prob_A_beats_B(model, feats[x], feats[y], a_home=False)
    return P


# --------------------------------------------------------------------------- #
# 3. Series and bracket simulation
# --------------------------------------------------------------------------- #
def sim_series(high: str, low: str, fmt: str, P: dict, rng: np.random.Generator) -> str:
    """
    Simulate one best-of-N series between the higher seed `high` and lower seed
    `low`, game by game, and return the winner. `high` hosts on 'H' games.
    """
    pattern = SERIES_FORMATS[fmt]
    need = len(pattern) // 2 + 1          # wins required (2, 3, or 4)
    hw = lw = 0
    for host in pattern:
        high_home = host == "H"
        p_high = P[(high, low, True)] if high_home else P[(high, low, False)]
        if rng.random() < p_high:
            hw += 1
        else:
            lw += 1
        if hw == need or lw == need:
            break
    return high if hw == need else low


def sim_bracket(seeds: list[str], P: dict, rng: np.random.Generator):
    """
    One full bracket. `seeds` is the ordered seed list (index 0 = #1 seed).
    Returns (finalist_1, finalist_2, champion). Higher seed = lower list index.
    """
    def higher(a, b):  # the better seed (earlier in the list) is the home side
        return (a, b) if seeds.index(a) < seeds.index(b) else (b, a)

    s = seeds
    # Round 1 (best-of-3): 1v8, 4v5 feed the top semifinal; 2v7, 3v6 the bottom.
    w18 = sim_series(*higher(s[0], s[7]), "R1", P, rng)
    w45 = sim_series(*higher(s[3], s[4]), "R1", P, rng)
    w27 = sim_series(*higher(s[1], s[6]), "R1", P, rng)
    w36 = sim_series(*higher(s[2], s[5]), "R1", P, rng)

    # Semifinals (best-of-5), no reseeding.
    f_top = sim_series(*higher(w18, w45), "SEMI", P, rng)
    f_bot = sim_series(*higher(w27, w36), "SEMI", P, rng)

    # Finals (best-of-7).
    champ = sim_series(*higher(f_top, f_bot), "FINALS", P, rng)
    return f_top, f_bot, champ


def run(n_sims: int = 20000, seed: int = 7):
    games = pd.read_csv(os.path.join(DATA, "all_games.csv"), parse_dates=["date"])
    standings = compute_standings(games)
    seeds = standings["team"].head(8).tolist()

    bundle = joblib.load(os.path.join(DATA, "models.joblib"))
    model = bundle["logistic"]  # primary predictor: calibrated & antisymmetric

    feats = current_team_features(games, seeds)
    P = build_prob_matrix(model, feats, seeds)

    rng = np.random.default_rng(seed)
    reach = Counter()
    champ = Counter()
    matchup = Counter()
    for _ in range(n_sims):
        f1, f2, c = sim_bracket(seeds, P, rng)
        reach[f1] += 1; reach[f2] += 1
        champ[c] += 1
        matchup[frozenset((f1, f2))] += 1

    res = pd.DataFrame({
        "seed": range(1, 9),
        "team": seeds,
        "conference": [CONFERENCE.get(t, "?") for t in seeds],
        "win_pct": [round(standings.loc[standings.team == t, "win_pct"].iloc[0], 3) for t in seeds],
        "p_reach_finals": [reach[t] / n_sims for t in seeds],
        "p_champion": [champ[t] / n_sims for t in seeds],
    }).sort_values("p_reach_finals", ascending=False).reset_index(drop=True)

    top_matchups = sorted(matchup.items(), key=lambda kv: -kv[1])[:6]
    top_matchups = [
        (tuple(sorted(pair, key=seeds.index)), cnt / n_sims) for pair, cnt in top_matchups
    ]

    res.to_csv(os.path.join(OUT, "finals_probabilities.csv"), index=False)
    return res, top_matchups, seeds, feats


def _print_report(res, top_matchups, n_sims):
    print(f"\n=== Bracket simulation: {n_sims:,} runs ===\n")
    print(f"{'Seed':<5}{'Team':<24}{'Conf':<6}{'Win%':>6}{'Reach Finals':>14}{'Champion':>11}")
    for _, r in res.iterrows():
        print(f"{r.seed:<5}{r.team:<24}{r.conference:<6}{r.win_pct:>6.3f}"
              f"{r.p_reach_finals:>13.1%}{r.p_champion:>11.1%}")
    print("\nMost likely Finals matchups:")
    for (a, b), p in top_matchups:
        print(f"  {a}  vs  {b}   {p:.1%}")


if __name__ == "__main__":
    N = 20000
    res, top_matchups, seeds, feats = run(n_sims=N)
    _print_report(res, top_matchups, N)
