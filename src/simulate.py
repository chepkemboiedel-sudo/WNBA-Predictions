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
import json
from collections import Counter, defaultdict

import joblib
import numpy as np
import pandas as pd

from features import FEATURE_COLS, PYTH_EXP
import availability as availability_mod

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
    "Connecticut Sun": "East", "Chicago Sky": "East", "Toronto Tempo": "East",
    "Los Angeles Sparks": "West", "Phoenix Mercury": "West",
    "Seattle Storm": "West", "Portland Fire": "West",
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


def playoff_seeds(games: pd.DataFrame, season: int = 2026) -> list[str]:
    """Use the actual first-round pairings once available to resolve tied seeds."""
    seeds = compute_standings(games, season)["team"].head(8).tolist()
    playoffs = games[(games.season == season) & games.is_playoff].sort_values("date")
    seen = set()
    for row in playoffs.itertuples():
        if row.home_team in seen or row.away_team in seen:
            continue
        high = seeds.index(row.home_team)
        if high >= 4:
            raise ValueError("First playoff host does not match a top-four seed.")
        low = 7 - high
        actual_low = seeds.index(row.away_team)
        seeds[low], seeds[actual_low] = seeds[actual_low], seeds[low]
        seen.update((row.home_team, row.away_team))
    return seeds


def completed_series(games: pd.DataFrame, seeds: list[str], season: int = 2026) -> dict:
    """Observed playoff wins, keyed by higher/lower seed, shared with the browser."""
    result = {}
    playoffs = games[(games.season == season) & games.is_playoff].sort_values("date")
    for row in playoffs.itertuples():
        high, low = sorted((row.home_team, row.away_team), key=seeds.index)
        key = high + "|" + low
        score = result.setdefault(key, {"hw": 0, "lw": 0})
        winner = row.home_team if row.home_win else row.away_team
        score["hw" if winner == high else "lw"] += 1
    return result


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


def build_prob_matrix(model, feats: dict, teams: list[str], availability: dict | None = None) -> dict:
    """Pre-compute P(x beats y | x at home) for every ordered pair -- 8x8x(home)."""
    P = {}
    availability = availability or {}
    enabled = availability.get("apply_adjustments", False)
    beta = availability.get("model", {}).get("margin_logit_coefficient", 0)
    for x in teams:
        for y in teams:
            if x == y:
                continue
            for home in (True, False):
                base = prob_A_beats_B(model, feats[x], feats[y], a_home=home)
                a = availability.get("teams",{}).get(x,{})
                b = availability.get("teams",{}).get(y,{})
                P[(x,y,home)] = availability_mod.adjust_probability(base,availability_mod.team_shift(a),availability_mod.team_shift(b),beta) if enabled else base
                next_game = availability.get("next_games",{}).get(x,{})
                if enabled and next_game.get("opponent") == y and next_game.get("home") == home:
                    P[(x,y,home,"next")] = availability_mod.adjust_probability(base,availability_mod.team_shift(a,"next_game"),availability_mod.team_shift(b,"next_game"),beta)
    return P


# --------------------------------------------------------------------------- #
# 3. Series and bracket simulation
# --------------------------------------------------------------------------- #
def sim_series(high: str, low: str, fmt: str, P: dict, rng: np.random.Generator,
               observed: dict | None = None) -> str:
    """
    Simulate one best-of-N series between the higher seed `high` and lower seed
    `low`, game by game, and return the winner. `high` hosts on 'H' games.
    """
    pattern = SERIES_FORMATS[fmt]
    need = len(pattern) // 2 + 1          # wins required (2, 3, or 4)
    score = (observed or {}).get(high + "|" + low, {})
    hw, lw = score.get("hw", 0), score.get("lw", 0)
    if hw >= need or lw >= need:
        return high if hw >= need else low
    for index,host in enumerate(pattern[hw + lw:]):
        high_home = host == "H"
        p_high = P.get((high,low,high_home,"next"),P[(high,low,high_home)]) if index == 0 else P[(high,low,high_home)]
        if rng.random() < p_high:
            hw += 1
        else:
            lw += 1
        if hw == need or lw == need:
            break
    return high if hw == need else low


def sim_bracket(seeds: list[str], P: dict, rng: np.random.Generator, observed=None):
    """
    One full bracket. `seeds` is the ordered seed list (index 0 = #1 seed).
    Returns (finalist_1, finalist_2, champion). Higher seed = lower list index.
    """
    def higher(a, b):  # the better seed (earlier in the list) is the home side
        return (a, b) if seeds.index(a) < seeds.index(b) else (b, a)

    s = seeds
    # Round 1 (best-of-3): 1v8, 4v5 feed the top semifinal; 2v7, 3v6 the bottom.
    w18 = sim_series(*higher(s[0], s[7]), "R1", P, rng, observed)
    w45 = sim_series(*higher(s[3], s[4]), "R1", P, rng, observed)
    w27 = sim_series(*higher(s[1], s[6]), "R1", P, rng, observed)
    w36 = sim_series(*higher(s[2], s[5]), "R1", P, rng, observed)

    # Semifinals (best-of-5), no reseeding.
    f_top = sim_series(*higher(w18, w45), "SEMI", P, rng, observed)
    f_bot = sim_series(*higher(w27, w36), "SEMI", P, rng, observed)

    # Finals (best-of-7).
    champ = sim_series(*higher(f_top, f_bot), "FINALS", P, rng, observed)
    return f_top, f_bot, champ


def run(n_sims: int = 20000, seed: int = 7):
    games = pd.read_csv(os.path.join(DATA, "all_games.csv"), parse_dates=["date"])
    standings = compute_standings(games)
    seeds = playoff_seeds(games)
    observed = completed_series(games, seeds)

    bundle = joblib.load(os.path.join(DATA, "models.joblib"))
    model = bundle["logistic"]  # primary predictor: calibrated & antisymmetric

    feats = current_team_features(games, seeds)
    availability = availability_mod.load_snapshot()
    P = build_prob_matrix(model, feats, seeds, availability)
    baseline_P = build_prob_matrix(model, feats, seeds)

    rng = np.random.default_rng(seed)
    reach = Counter()
    champ = Counter()
    matchup = Counter()
    for _ in range(n_sims):
        f1, f2, c = sim_bracket(seeds, P, rng, observed)
        reach[f1] += 1; reach[f2] += 1
        champ[c] += 1
        matchup[frozenset((f1, f2))] += 1

    baseline_reach, baseline_champ = Counter(), Counter()
    baseline_rng = np.random.default_rng(seed)
    for _ in range(n_sims):
        f1,f2,c = sim_bracket(seeds,baseline_P,baseline_rng,observed)
        baseline_reach[f1]+=1;baseline_reach[f2]+=1;baseline_champ[c]+=1

    res = pd.DataFrame({
        "seed": range(1, 9),
        "team": seeds,
        "conference": [CONFERENCE.get(t, "?") for t in seeds],
        "win_pct": [round(standings.loc[standings.team == t, "win_pct"].iloc[0], 3) for t in seeds],
        "p_reach_finals": [reach[t] / n_sims for t in seeds],
        "p_champion": [champ[t] / n_sims for t in seeds],
        "p_reach_finals_baseline": [baseline_reach[t] / n_sims for t in seeds],
        "p_champion_baseline": [baseline_champ[t] / n_sims for t in seeds],
    }).sort_values("p_reach_finals", ascending=False).reset_index(drop=True)

    top_matchups = sorted(matchup.items(), key=lambda kv: -kv[1])[:6]
    top_matchups = [
        (tuple(sorted(pair, key=seeds.index)), cnt / n_sims) for pair, cnt in top_matchups
    ]

    os.makedirs(OUT, exist_ok=True)
    res.to_csv(os.path.join(OUT, "finals_probabilities.csv"), index=False)
    conference_counts = Counter()
    for pair, count in matchup.items():
        conferences = {CONFERENCE.get(t, "?") for t in pair}
        category = "both_west" if conferences == {"West"} else (
            "both_east" if conferences == {"East"} else "mixed")
        conference_counts[category] += count
    forecast = {
        "n_sims": n_sims,
        "data_through": games[games.season == 2026].date.max().strftime("%Y-%m-%d"),
        "game_count": len(games),
        "completed_playoff_games": int(((games.season == 2026) & games.is_playoff).sum()),
        "observed_series": observed,
        "probability_model": "availability-experimental" if availability.get("apply_adjustments") else "score-only",
        "availability": {key:availability.get(key) for key in ("status","fetched_at","apply_adjustments","message","model","boxscore_coverage")},
        "top_matchups": [{"teams": list(pair), "probability": probability}
                         for pair, probability in top_matchups],
        "conferences": {key: conference_counts[key] / n_sims
                        for key in ("both_west", "mixed", "both_east")},
    }
    with open(os.path.join(OUT, "forecast.json"), "w", encoding="utf-8") as f:
        json.dump(forecast, f, indent=2)
        f.write("\n")
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
