"""One-time local source migration; deliberately excluded from publication."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def edit(name, changes):
    path=ROOT/name
    text=path.read_text(encoding="utf-8")
    for old,new in changes:
        if old not in text:
            raise ValueError(f"Missing replacement in {name}: {old[:90]}")
        text=text.replace(old,new)
    path.write_text(text,encoding="utf-8")

edit("src/player_context.py", [('groupby(["player_id","name"])','groupby(["player_id","player"])')])
edit("src/fetch_espn.py", [
 ('def fetch_season(year: int, force: bool = False)', 'def fetch_season(year: int, force: bool = False, allow_empty: bool = False)'),
 ('    else:\n        raise RuntimeError(f"No completed games returned for {year}; cache preserved.")', '    else:\n        if allow_empty and not os.path.exists(cache):\n            return pd.DataFrame()\n        raise RuntimeError(f"No completed games returned for {year}; cache preserved.")'),
 ('end: int = 2026','end: int | None = None'),
 ('    frames = []\n    for yr', '    end = end or datetime.now(timezone.utc).year\n    frames = []\n    for yr'),
 ('frames.append(fetch_season(yr, force=force))', 'frame = fetch_season(yr, force=force, allow_empty=(yr == end))\n        if not frame.empty:\n            frames.append(frame)')])
edit("run_all.py", [('start=2016, end=2026, refresh_current=True','start=2016, refresh_current=True')])
edit("src/simulate.py", [
 ('import availability as availability_mod', 'import availability as availability_mod\nfrom seasons import forecast_season, context\nimport promotion\nfrom pathlib import Path'),
 ('season: int = 2026','season: int | None = None'),
 ('    reg = games[(games.season == season)', '    season = season or forecast_season(games)\n    reg = games[(games.season == season)'),
 ('    seeds = compute_standings(games, season)', '    season = season or forecast_season(games)\n    seeds = compute_standings(games, season)'),
 ('    result = {}\n    playoffs', '    season = season or forecast_season(games)\n    result = {}\n    playoffs'),
 ('    # Published predictions always use score-only probabilities. A verified\n    # player feed makes the experimental comparison available, never default.\n    P = build_prob_matrix(model, feats, seeds)\n    optional_P = build_prob_matrix(model, feats, seeds, availability)',
  '    season = forecast_season(games)\n    if availability.get("season") != season:\n        availability = dict(availability, apply_adjustments=False)\n    policy = promotion.current(Path(DATA).parent, availability, season)\n    baseline_P = build_prob_matrix(model, feats, seeds)\n    optional_P = build_prob_matrix(model, feats, seeds, availability)\n    P = optional_P if policy["usable"] else baseline_P'),
 ('    optional_reach, optional_champ = Counter(), Counter()', '    baseline_reach, baseline_champ = Counter(), Counter()\n    baseline_rng = np.random.default_rng(seed)\n    for _ in range(n_sims):\n        f1,f2,c = sim_bracket(seeds,baseline_P,baseline_rng,observed)\n        baseline_reach[f1]+=1;baseline_reach[f2]+=1;baseline_champ[c]+=1\n    optional_reach, optional_champ = Counter(), Counter()'),
 ('"p_reach_finals_baseline": [reach[t]', '"p_reach_finals_baseline": [baseline_reach[t]'),
 ('"p_champion_baseline": [champ[t]', '"p_champion_baseline": [baseline_champ[t]'),
 ('games.season == 2026','games.season == season'),
 ('"probability_model": "score-only",\n        "injury_adjustment_default": False,', '"season": season, "season_context": context(games),\n        "promotion": policy,\n        "probability_model": "injury-adjusted" if policy["usable"] else "score-only",\n        "injury_adjustment_default": policy["usable"],')])
edit("src/model.py", [
 ('    matchups = build_matchup_table(games)', '    matchups = build_matchup_table(games)\n    from seasons import forecast_season\n    season = forecast_season(games)'),
 ('train_seasons=range(2016, 2024), test_seasons=range(2024, 2026)', 'train_seasons=range(2016, season-2), test_seasons=range(season-2, season)'),
 ('matchups.season.isin(range(2024, 2026))','matchups.season.isin(range(season-2, season))'),
 ('matchups.season <= 2025','matchups.season < season')])
edit("src/availability.py", [
 ('MODEL_VERSION = "participation-ridge-v1"', 'MODEL_VERSION = "participation-ridge-minutes-v2"'),
 ('from app_data import atomic_json', 'from app_data import atomic_json\nfrom seasons import latest\nfrom player_context import minute_limit, projected_rotation'),
 ('    target = games[((games.season == 2025) & ~games.is_playoff) | (games.season == 2026)]', '    season = latest(games)\n    target = games[((games.season == season-1) & ~games.is_playoff) | (games.season == season)]'),
 ('    regular = boxscores[~boxscores.is_playoff].copy()', '    season = latest(games)\n    regular = boxscores[(~boxscores.is_playoff) & boxscores.season.isin([season-1,season])].copy()'),
 ('matchups.season.isin([2025,2026])','matchups.season.isin([season-1,season])'),
 ('matchups.season <= 2025','matchups.season < season'),
 ('"training_seasons":[2025,2026]','"training_seasons":[season-1,season]'),
 ('    path = DATA / "player_availability.json"','    season = latest(games)\n    path = DATA / "player_availability.json"'),
 ('"season":2026','"season":season'),
 ('!= 2026','!= season'),
 ('/roster?season=2026','/roster?season={season}'),
 ('boxes.season==2026','boxes.season==season'),
 ('games.season==2026','games.season==season'),
 ('                if not ready:\n                    penalty=0.0', '                typical = float(appearances.minutes.mean()) if gp else 0\n                cap = minute_limit(report,now,next_games.get(name),typical,last_played) if report else None\n                if cap and evaluated["scope"]=="none" and len(owners[aid])==1:\n                    evaluated={"scope":"next_game","reason":"Explicit fresh minute restriction; fractional absence estimate for next game only."}\n                    penalty=absence_penalty(effects.get(aid,0),gp/team_games if team_games else 0)*cap["fraction_missing"]\n                if not ready:\n                    penalty=0.0'),
 ('"effect_points":effects.get(aid,0),', '"minute_limit":cap,"report_comment":report.get("shortComment","") if report else "",\n                             "effect_points":effects.get(aid,0),'),
 ('"adjustment_ready":ready,"missing_boxscores":len(missing_for_team),','"adjustment_ready":ready,"missing_boxscores":len(missing_for_team),\n                                   "rotation":projected_rotation(boxes,name,season),')])
edit("src/evaluation.py", [
 ('if tip.year!=2026 or games.date.max().date()>now.date():','if tip.year!=int(games.season.max()) or snapshot.get("season",tip.year)!=tip.year or games.date.max().date()>now.date():'),
 ('no statistical threshold automatically promotes injuries.', 'automatic promotion is evaluated separately using fixed prospective blocks; historical comparisons cannot promote a model.')])
edit("src/app_data.py", [
 ('"source": source, "n_sims": forecast["n_sims"],', '"source": source, "season":forecast.get("season",int(forecast["data_through"][:4])), "n_sims": forecast["n_sims"],'),
 ('current = games[games.season == 2026]', 'current = games[games.season == int(results.attrs.get("season",games.season.max()))]' ) if False else ('    current = games[games.season == 2026]\n    return', '    current = games[games.season == forecast.get("season",int(games.season.max()))]\n    return'),
 ('"season": 2026','"season": forecast.get("season",int(games.season.max()))'),
 ('    current = games[games.season == 2026].sort_values', '    from seasons import forecast_season\n    current = games[games.season == forecast_season(games)].sort_values')])
edit("src/explain.py", [('matchups.season <= 2025','matchups.season < int(games.season.max())')])
edit("src/app_features.py", [
 ('>2026 coverage<', '>{health.get("season",2026)} coverage<'),
 ('in the 2026 data.', 'in the current forecast season.'),
 ('<p class="eyebrow">2026 team profile', '<p class="eyebrow">{data["health"]["season"]} team profile'),
 ('const row=entry.teams.find(t=>t.team===team);', 'if((entry.season || Number(entry.data_through.slice(0,4)))!==APP.health.season)return [];const row=entry.teams.find(t=>t.team===team);')])
