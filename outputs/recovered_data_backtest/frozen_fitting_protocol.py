"""Frozen original historical fitting protocol; no production model changes.
Source: dbab1765e8ec4dcc426a25830dc332791f49524e, src/availability.py.
"""
import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from features import build_matchup_table
MAX_PLAYER_POINTS = 4.0
MAX_TEAM_POINTS = 6.0
MODEL_VERSION = "participation-ridge-v1"

def fit_effects(games, boxscores):
    regular = boxscores[~boxscores.is_playoff].copy()
    played = regular[regular.minutes > 0]
    counts = played.groupby(["season","team","player_id"]).game_id.nunique().to_dict()
    team_counts = regular.groupby(["season","team"]).game_id.nunique().to_dict()
    mean = {key:value / team_counts[key[:2]] for key,value in counts.items()}
    ids = sorted(played.player_id.unique())
    columns = {aid:index for index,aid in enumerate(ids)}
    lineups = played.groupby(["game_id","team"]).player_id.apply(set).to_dict()
    mean_by_team = {}
    for (season,team,aid), value in mean.items():
        mean_by_team.setdefault((season,team), {})[aid] = value
    matchups = build_matchup_table(games)
    rows = matchups[(matchups.season.isin([2025,2026])) & ~matchups.is_playoff & (matchups.home == 1)]
    scores = games.set_index(games.game_id.astype(str))
    x, margins, form = [], [], []
    for row in rows.itertuples():
        gid = str(row.game_id)
        if (gid,row.team) not in lineups or (gid,row.opp) not in lineups:
            continue
        vector = np.zeros(len(ids))
        for team,sign in ((row.team,1),(row.opp,-1)):
            for aid,value in mean_by_team.get((row.season,team), {}).items():
                vector[columns[aid]] -= sign * value
            for aid in lineups[(gid,team)]:
                vector[columns[aid]] += sign
        game = scores.loc[gid]
        x.append(vector)
        margins.append(float(game.home_score - game.away_score))
        form.append([row.d_pt_diff])
    if len(x) < 100:
        raise ValueError("Insufficient complete games to estimate player participation effects")
    baseline = Ridge(alpha=10).fit(form, margins)
    residuals = np.asarray(margins) - baseline.predict(form)
    model = Ridge(alpha=30, fit_intercept=False).fit(np.asarray(x), residuals)
    support = {}
    for (season,team,aid), appearances in counts.items():
        if appearances >= 3 and team_counts[(season,team)] - appearances >= 3:
            support[aid] = True
    effects = {aid:round(float(np.clip(model.coef_[index],0,MAX_PLAYER_POINTS)),4)
               if support.get(aid) else 0.0 for aid,index in columns.items()}
    old = matchups[matchups.season <= 2025]
    mapper = LogisticRegression(C=1, max_iter=1000).fit(old[["d_pt_diff","home"]],old.target)
    beta = float(mapper.coef_[0][0])
    if not 0 < beta < .5:
        raise ValueError("Invalid point-margin to probability conversion")
    return effects, {"version":MODEL_VERSION,"experimental":True,"training_games":len(x),
                     "training_seasons":[2025,2026],"ridge_alpha":30,
                     "max_player_points":MAX_PLAYER_POINTS,"max_team_points":MAX_TEAM_POINTS,
                     "margin_logit_coefficient":beta,"players_with_comparison":len(support)}

