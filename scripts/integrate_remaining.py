from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def edit(name,changes):
    p=ROOT/name;t=p.read_text(encoding="utf-8")
    for old,new in changes:
        if old not in t:raise ValueError(f"{name}: missing {old[:100]}")
        t=t.replace(old,new)
    p.write_text(t,encoding="utf-8")

edit("src/build_site.py",[
 ('import backtest_ui as BT','import backtest_ui as BT\nimport live_ui as LIVE\nimport operations\nfrom seasons import forecast_season'),
 ('standings = S.compute_standings(games)','season = forecast_season(games)\nstandings = S.compute_standings(games)'),
 ('S.CONFERENCE[t]','S.CONFERENCE.get(t,"Unknown")'),
 ('results = pd.read_csv(ROOT / "outputs" / "finals_probabilities.csv")','results = pd.read_csv(ROOT / "outputs" / "finals_probabilities.csv")\nDATA["default_model"] = forecast["probability_model"]\nDATA["prob"] = PROB if forecast["injury_adjustment_default"] else BASE_PROB\noperations.update(ROOT,games,results,forecast,player_snapshot)'),
 ('let applyAvailability = false;', 'let applyAvailability = D.default_model === "injury-adjusted";'),
 ('const availabilityToggle=document.getElementById(\'use-availability\');', 'const availabilityToggle=document.getElementById(\'use-availability\');\navailabilityToggle.checked=applyAvailability;'),
 ('{\'\' if player_snapshot.get(\'apply_adjustments\') else \'disabled\'}>', '{\'checked\' if forecast["injury_adjustment_default"] else \'\'} {\'\' if player_snapshot.get(\'apply_adjustments\') else \'disabled\'}>'),
 ('BODY += UI.health_section(DATA["health"])', 'BODY += LIVE.section(player_snapshot,forecast)\nBODY += UI.health_section(DATA["health"])'),
 ('+ JS + UI.JS + BT.JS + UI.POLL_JS +', '+ JS + UI.JS + BT.JS + UI.POLL_JS + LIVE.JS +'),
 ('+ data_json + ";</script>', '+ data_json + ";window.__PLAYER_CONTEXT__=" + LIVE.payload(player_snapshot) + ";</script>'),
 ('TITLE = "<title>2026 WNBA Finals Forecast</title>"','TITLE = f"<title>{season} WNBA Finals Forecast</title>"'),
 ('2026 WNBA · Playoff Forecast','{season} WNBA · Playoff Forecast'),
 ('Score-only predictions are the default, validated on 2016–2025. Injury adjustments are optional and experimental.', 'Published model: {forecast["probability_model"]}. Score-model validation uses held-out seasons through {season-1}. Injury adjustments require prospective evidence before becoming default.'),
 ('2016–2026</span>','2016–{season}</span>'),
 ('DESC = ("Interactive 2026 WNBA Finals forecast', 'DESC = (f"Interactive {season} WNBA Finals forecast'),
 ('\'<meta property="og:title" content="2026 WNBA Finals Forecast">\\n\'', 'f\'<meta property="og:title" content="{season} WNBA Finals Forecast">\\n\''),
 ('# 2026 WNBA forecast', '# {season} WNBA forecast'),
 ('games across 2016–2026,','games across 2016–{season},'),
 ('completed 2026 playoff games.', 'completed {season} playoff games.'),
 ('fitted to 2016–2025 score-based', 'fitted to 2016–{season-1} score-based'),
 ('validation trains on 2016–2023 and tests on 2024–2025.', 'validation trains through {season-3} and tests on {season-2}–{season-1}.'),
 ('Published forecasts and new history entries use the score-only model by default.', 'Published model: {forecast["probability_model"]}. Automatic selection uses fixed prospective blocks, never the retrospective study.'),
 ('It is available through an unchecked interactive toggle.', 'The interactive toggle starts at the published model choice.')])
edit("src/app_features.py",[('<a href="/#availability">Availability</a>','<a href="/#availability">Availability</a><a href="/#live">Live context</a>')])
edit("src/availability_ui.py",[
 ('<div class="report-note">{escape(player[\'detail\'])}</div>', '<div class="report-note">{escape(player[\'detail\'])}</div><div class="report-note">{escape(str(player.get("minute_limit",{}).get("minutes"))+"-minute limit") if player.get("minute_limit") else "No verified minute cap"}</div>'),
 ('<p>Minute restrictions and mid-game injuries are not forecast.</p>', '<p>Fresh, explicitly stated numeric minute limits can receive a fractional next-game penalty. <a href="#live">Live context</a> shows projected rotations and a separate illustrative mid-game injury scenario. These additions require their own prospective validation.</p>'),
 ('2026 regular-season box scores','{availability.get("season",2026)} regular-season box scores'),
 ('games across 2025–26.', 'games across the current and preceding season.'),
 ('games from 2025–26.', 'games from the current and preceding season.')])
edit("src/explain.py",[
 ('m.season <= 2025','m.season < int(games.season.max())'),
 ('local_matchup(model, feats, "Minnesota Lynx", "Las Vegas Aces", True,','local_matchup(model, feats, seeds[0], seeds[1], True,'),
 ('local_matchup(model, feats, "Minnesota Lynx", "Indiana Fever", True,','local_matchup(model, feats, seeds[0], seeds[3], True,'),
 ('local_matchup(model, feats, "Las Vegas Aces", "Golden State Valkyries", True,','local_matchup(model, feats, seeds[1], seeds[2], True,')])
edit("src/visuals.py",[('"2026 WNBA — simulated', '"WNBA — simulated')])
edit("src/compare_odds.py",[
 ('season: int = 2026','season: int | None = None'),
 ('    cache = os.path.join(DATA, "market_odds.csv")', '    if season is None:\n        from seasons import forecast_season\n        season = forecast_season(pd.read_csv(os.path.join(DATA,"all_games.csv")))\n    cache = os.path.join(DATA, "market_odds.csv")'),
 ('Model vs. sportsbook — 2026 WNBA title odds','Model vs. sportsbook — WNBA title odds')])
edit("scripts/collect_historical_injuries.py",[
 ('row["season"] != "2026"','int(row["season"]) < 2026'),
 ('(now.date()-datetime.fromisoformat(day).date()).days>7', '(attempted and now-attempted<timedelta(days=7))')])
# Re-check failed archived reports weekly; retain verified files and frozen rows.
edit("scripts/verify_forecast.py",[
 ('    if forecast.get("probability_model")!="score-only" or forecast.get("injury_adjustment_default") is not False:\n        raise ValueError("Published forecasts must use the score-only default.")', '    from promotion import current\n    import availability as A\n    decision=current(ROOT,A.load_snapshot(),forecast.get("season",2026))\n    promoted=decision["usable"]\n    expected_model="injury-adjusted" if promoted else "score-only"\n    if forecast.get("probability_model")!=expected_model or forecast.get("injury_adjustment_default")!=promoted:\n        raise ValueError("Published default disagrees with independently re-evaluated promotion evidence.")'),
 ('if not results.p_champion.equals(results.p_champion_baseline) or not results.p_reach_finals.equals(results.p_reach_finals_baseline):', 'if not promoted and (not results.p_champion.equals(results.p_champion_baseline) or not results.p_reach_finals.equals(results.p_reach_finals_baseline)):'),
 ('if embedded.get("default_model")!="score-only" or embedded["prob"]!=embedded["prob_base"]:', 'if embedded.get("default_model")!=expected_model or embedded["prob"]!=embedded["prob_availability" if promoted else "prob_base"]:'),
 ('if not optional_input or "checked" in optional_input[0]:','if not optional_input or ("checked" in optional_input[0])!=promoted:'),
 ('if latest.get("probability_model")!="score-only":', 'if latest.get("probability_model")!=expected_model:'),
 ('pd.read_csv(ROOT / "data/games_2026.csv").home_team','pd.read_csv(ROOT / ("data/games_"+str(forecast.get("season",2026))+".csv")).home_team')])
edit(".github/workflows/daily-refresh.yml",[
 ('      statuses: read','      statuses: read\n      issues: write'),
 ('          node tests/test_backtest_browser.cjs','          node tests/test_backtest_browser.cjs\n          node tests/test_live_monitor.cjs'),
 ('      - name: Commit refreshed outputs', '      - name: Check cloud alerts\n        if: github.event_name != \'pull_request\'\n        env:\n          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n          ALERT_RECIPIENT: chepkemboiedel-sudo\n        run: node scripts/cloud-monitor.cjs\n\n      - name: Commit refreshed outputs')])
