"""Current ESPN rosters and a conservative, experimental absence adjustment.

The score-only model remains the validated baseline. Player effects are shrunken
associations between observed participation and score residuals, not causal or
independently calibrated injury estimates. Old game-specific reports never
become indefinite absences; long-term absence already in team form is discounted.
"""
from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression, Ridge

from app_data import atomic_json
from seasons import latest as latest_season
from player_context import minute_limit, projected_rotation
from features import build_matchup_table

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
API = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
MODEL_VERSION = "participation-ridge-minutes-v2"
MAX_PLAYER_POINTS = 4.0
MAX_TEAM_POINTS = 6.0
REPORT_HOURS = 72


def utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=timezone.utc) if len(str(value)) == 10 else datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def get_json(url):
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"User-Agent":"WNBA forecast research"}, timeout=25)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def number(value):
    try:
        text = str(value)
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            return float(minutes) + float(seconds) / 60
        return float(text.replace("+", ""))
    except (ValueError, TypeError):
        return 0.0


def athlete_id(athlete):
    if athlete.get("id"):
        return str(athlete["id"])
    for link in athlete.get("links", []):
        match = re.search(r"/id/(\d+)", link.get("href", ""))
        if match:
            return match[1]
    return None


def parse_boxscore(payload, game):
    header = payload.get("header", {})
    if str(header.get("id")) != str(game.game_id) or header.get("season", {}).get("year") != int(game.season):
        raise ValueError("Box score event or season mismatch")
    competition = header.get("competitions", [{}])[0]
    if not competition.get("status", {}).get("type", {}).get("completed"):
        raise ValueError("Box score is not completed")
    rows = []
    for side in payload.get("boxscore", {}).get("players", []):
        team = side["team"]["displayName"]
        seen = set()
        for table in side.get("statistics", []):
            labels = table.get("labels", [])
            if "MIN" not in labels:
                continue
            for entry in table.get("athletes", []):
                athlete = entry["athlete"]
                aid = str(athlete["id"])
                if aid in seen:
                    continue
                seen.add(aid)
                stats = dict(zip(labels, entry.get("stats", [])))
                # ESPN's `active` flag can be false even when a player played.
                minutes = number(stats.get("MIN", 0)) if not entry.get("didNotPlay") else 0.0
                rows.append({"game_id":str(game.game_id),"season":int(game.season),"date":str(game.date)[:10],
                             "started_at":competition.get("date", ""),"is_playoff":bool(game.is_playoff),
                             "team":team,"player_id":aid,"player":athlete["displayName"],
                             "minutes":minutes,"points":number(stats.get("PTS",0)),
                             "rebounds":number(stats.get("REB",0)),"assists":number(stats.get("AST",0))})
    for team in (game.home_team, game.away_team):
        side = [row for row in rows if row["team"] == team]
        if sum(row["minutes"] > 0 for row in side) < 5 or sum(row["minutes"] for row in side) < 180:
            raise ValueError("Incomplete team minutes in box score")
    return rows


def fetch_boxscores(games):
    path = DATA / "player_game_stats.csv"
    cached = pd.read_csv(path, dtype={"game_id":str,"player_id":str}) if path.exists() else pd.DataFrame()
    season = latest_season(games)
    target = games[((games.season == season-1) & ~games.is_playoff) | (games.season == season)]
    completed = set(cached.game_id) if not cached.empty else set()
    missing = [row for row in target.itertuples() if str(row.game_id) not in completed]
    rows, failures = [], []
    print(f"  Player box scores: {len(missing)} new games; {len(completed)} cached", flush=True)

    def fetch(game):
        archive=DATA/"recovery"/f"boxscore_{game.game_id}.json"
        if archive.exists():
            from recovered_data import load_verified_boxscore
            return load_verified_boxscore(DATA.parent,game)
        return parse_boxscore(get_json(API + f"/summary?event={game.game_id}"), game)

    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(fetch, game):game for game in missing}
        for index, future in enumerate(as_completed(pending), 1):
            try:
                rows.extend(future.result())
            except Exception as error:
                failures.append(str(pending[future].game_id))
                print(f"  Box score {pending[future].game_id} not usable: {error}", flush=True)
            if index % 50 == 0:
                print(f"  Player box scores: {index}/{len(missing)} checked", flush=True)
    combined = pd.concat([cached, pd.DataFrame(rows)], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(["game_id","team","player_id"]).sort_values(["date","game_id","team","player_id"])
        combined.to_csv(str(path) + ".tmp", index=False)
        Path(str(path) + ".tmp").replace(path)
    expected = set(target.game_id.astype(str))
    covered = set(combined.game_id.astype(str)) if not combined.empty else set()
    return combined, {"expected_games":len(expected),"covered_games":len(expected & covered),
                      "missing_games":sorted(expected - covered)}


def fit_effects(games, boxscores):
    season = latest_season(games)
    regular = boxscores[(~boxscores.is_playoff) & boxscores.season.isin([season-1,season])].copy()
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
    rows = matchups[(matchups.season.isin([season-1,season])) & ~matchups.is_playoff & (matchups.home == 1)]
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
    old = matchups[matchups.season < season]
    mapper = LogisticRegression(C=1, max_iter=1000).fit(old[["d_pt_diff","home"]],old.target)
    beta = float(mapper.coef_[0][0])
    if not 0 < beta < .5:
        raise ValueError("Invalid point-margin to probability conversion")
    return effects, {"version":MODEL_VERSION,"experimental":True,"training_games":len(x),
                     "training_seasons":[season-1,season],"ridge_alpha":30,
                     "max_player_points":MAX_PLAYER_POINTS,"max_team_points":MAX_TEAM_POINTS,
                     "margin_logit_coefficient":beta,"players_with_comparison":len(support)}


def evaluate_report(report, *, now, last_played=None, next_game=None):
    """A fresh fetch is not evidence that an old individual injury is current."""
    status = str(report.get("status", "Unknown"))
    date = utc(report.get("date"))
    details = report.get("details", {})
    fantasy = details.get("fantasyStatus", {}).get("abbreviation", "")
    season_out = fantasy.upper() == "OFS"
    if status.lower() not in ("out","suspended"):
        return {"scope":"none","reason":"Uncertain availability is displayed without assuming an absence."}
    if not date or date > now + timedelta(hours=1):
        return {"scope":"none","reason":"Report timestamp is missing or inconsistent."}
    appeared = utc(last_played)
    if appeared and appeared > date:
        return {"scope":"none","reason":"A later game appearance conflicts with this old report; no penalty applied."}
    if season_out:
        return {"scope":"long_term","reason":"Reported out for the season; prior missed time is discounted."}
    scheduled = utc((next_game or {}).get("date"))
    return_date = utc(details.get("returnDate"))
    if now-date > timedelta(hours=REPORT_HOURS):
        return {"scope":"none","reason":"Old game-specific report; needs a new update before changing the forecast."}
    if not scheduled or scheduled > date + timedelta(hours=REPORT_HOURS):
        return {"scope":"none","reason":"No upcoming game within the report's 72-hour applicability window."}
    if return_date and return_date.date() <= scheduled.date():
        return {"scope":"none","reason":"Expected return date reaches the next game; await a new status report."}
    return {"scope":"next_game","reason":"Fresh confirmed absence; applied only to the next scheduled game."}


def absence_penalty(effect, baseline_fraction):
    return max(0.0,min(MAX_PLAYER_POINTS,float(effect))) * max(0.0,min(1.0,float(baseline_fraction)))


def team_shift(team, scope="long_term"):
    if team.get("adjustment_ready") is False:
        return 0.0
    allowed = {"long_term"} if scope == "long_term" else {"long_term","next_game"}
    penalty=min(MAX_TEAM_POINTS,sum(p.get("extra_absence_points",0) for p in team.get("players",[]) if p.get("scope") in allowed))
    return -penalty if penalty else 0.0


def adjust_probability(probability, shift_a, shift_b, beta):
    p = float(np.clip(probability,1e-6,1-1e-6))
    value = math.log(p/(1-p)) + beta*(shift_a-shift_b)
    return 1/(1+math.exp(-value))


def load_snapshot(now=None):
    path = DATA / "player_availability.json"
    if not path.exists():
        return {"status":"unavailable","apply_adjustments":False,"teams":{},"message":"Player data has not been fetched; using score-only forecasts."}
    value = json.loads(path.read_text(encoding="utf-8"))
    age = (now or datetime.now(timezone.utc)) - (utc(value.get("fetched_at")) or datetime.min.replace(tzinfo=timezone.utc))
    if age > timedelta(hours=36):
        value["status"] = "stale"
        value["apply_adjustments"] = False
        value["message"] = "Player feed is more than 36 hours old; using score-only forecasts."
    return value


def refresh(games=None):
    now = datetime.now(timezone.utc)
    games = games if games is not None else pd.read_csv(DATA/"all_games.csv",parse_dates=["date"])
    season = latest_season(games)
    path = DATA / "player_availability.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    value = {"version":1,"fetched_at":now.isoformat().replace("+00:00","Z"),"season":season,
             "source":"ESPN roster, injury, and completed box-score feeds",
             "source_url":"https://www.espn.com/wnba/injuries","status":"live",
             "apply_adjustments":False,"teams":{},"message":"Player feeds retrieved successfully."}
    try:
        feed = get_json(API+"/injuries?limit=1000")
        if feed.get("status") != "success" or feed.get("season",{}).get("year") != season:
            raise ValueError("Injury feed season or status mismatch")
        value["source_timestamp"] = feed.get("timestamp")
        teams = get_json(API+"/teams?limit=100")["sports"][0]["leagues"][0]["teams"]
        reports = {str(row["id"]):row.get("injuries",[]) for row in feed.get("injuries",[])}
        raw_rosters = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(get_json,API+f'/teams/{row["team"]["id"]}/roster?season={season}'):row["team"] for row in teams}
            for future in as_completed(futures):
                team = futures[future]
                roster = future.result()
                if roster.get("season",{}).get("year") != season or not roster.get("athletes"):
                    raise ValueError("Missing or wrong-season roster")
                raw_rosters[team["displayName"]] = (team,roster)
        boxes, coverage = fetch_boxscores(games)
        value["boxscore_coverage"] = coverage
        enough_history = coverage["expected_games"] > 0 and coverage["covered_games"] / coverage["expected_games"] >= .98
        effects, model = fit_effects(games,boxes) if enough_history else ({},{})
        value["model"] = model
        next_games = {}
        for offset in range(8):
            day = (now + timedelta(days=offset)).strftime("%Y%m%d")
            schedule = get_json(API+f"/scoreboard?dates={day}&limit=100")
            for event in schedule.get("events",[]):
                comp = event["competitions"][0]
                if comp["status"]["type"].get("completed") or event.get("season",{}).get("type") not in (2,3):
                    continue
                competitors = comp["competitors"]
                for competitor in competitors:
                    team = competitor["team"]["displayName"]
                    opponent = next(c["team"]["displayName"] for c in competitors if c is not competitor)
                    if team not in next_games:
                        next_games[team] = {"event_id":str(event["id"]),"date":event["date"],"opponent":opponent,"home":competitor["homeAway"]=="home","is_playoff":event.get("season",{}).get("type")==3}
        value["next_games"] = next_games
        regular = boxes[(boxes.season==season) & ~boxes.is_playoff] if not boxes.empty else pd.DataFrame()
        owners = {}
        for name,(_,roster) in raw_rosters.items():
            for athlete in roster["athletes"]:
                owners.setdefault(str(athlete["id"]),[]).append(name)
        for name,(team,roster) in raw_rosters.items():
            rows = []
            source_reports = {athlete_id(r.get("athlete",{})):r for r in reports.get(str(team["id"]),[]) if athlete_id(r.get("athlete",{}))}
            team_games = int(((games.season==season)&~games.is_playoff&((games.home_team==name)|(games.away_team==name))).sum())
            missing_for_team = games[(games.season==season)&games.game_id.astype(str).isin(coverage["missing_games"])&((games.home_team==name)|(games.away_team==name))]
            ready = missing_for_team.empty and bool(model)
            for athlete in roster["athletes"]:
                aid = str(athlete["id"])
                report = source_reports.get(aid)
                if not report and athlete.get("injuries"):
                    report = athlete["injuries"][0]
                appearances = regular[(regular.team==name)&(regular.player_id==aid)&(regular.minutes>0)] if not regular.empty else pd.DataFrame()
                gp = len(appearances)
                latest = boxes[(boxes.player_id==aid)&(boxes.minutes>0)] if not boxes.empty else pd.DataFrame()
                last_played = str(latest.sort_values("date").iloc[-1].started_at) if not latest.empty else None
                evaluated = evaluate_report(report,now=now,last_played=last_played,next_game=next_games.get(name)) if report else {"scope":"none","reason":"No injury listed in the feed; this is not a guaranteed game lineup."}
                if len(owners[aid])>1:
                    evaluated={"scope":"none","reason":"Player appears on multiple season rosters; assignment is ambiguous."}
                penalty = absence_penalty(effects.get(aid,0),gp/team_games if team_games else 0) if evaluated["scope"]!="none" else 0
                typical = float(appearances.minutes.mean()) if gp else 0
                cap = minute_limit(report,now,next_games.get(name),typical,last_played) if report else None
                if cap and evaluated["scope"]=="none" and len(owners[aid])==1:
                    evaluated={"scope":"next_game","reason":"Explicit fresh minute restriction; fractional absence estimate for next game only."}
                    penalty=absence_penalty(effects.get(aid,0),gp/team_games if team_games else 0)*cap["fraction_missing"]
                if not ready:
                    penalty=0.0
                    evaluated["reason"]+=" Team player history is incomplete; no adjustment is applied."
                if evaluated["scope"]!="none" and gp==0:
                    evaluated["reason"]="No regular-season appearances for this team; the score baseline already reflects the absence."
                elif evaluated["scope"]!="none" and effects.get(aid,0)==0:
                    evaluated["reason"]+=" No reliable positive participation effect was estimated."
                rows.append({"id":aid,"name":athlete["displayName"],"position":athlete.get("position",{}).get("abbreviation","—"),
                             "jersey":athlete.get("jersey",""),"status":report.get("status","Unknown") if report else "No report",
                             "report_date":report.get("date") if report else None,
                             "detail":report.get("details",{}).get("type","Not specified") if report else "—",
                             "source_url":f"https://www.espn.com/wnba/player/_/id/{aid}",
                             "games_played":gp,"minutes":round(float(appearances.minutes.mean()),1) if gp else None,
                             "points":round(float(appearances.points.mean()),1) if gp else None,
                             "baseline_participation":round(gp/team_games,4) if team_games else 0,
                             "minute_limit":cap,"report_comment":report.get("shortComment","") if report else "",
                             "effect_points":effects.get(aid,0),"extra_absence_points":round(penalty,4),**evaluated})
            previous_ids = {p["id"] for p in previous.get("teams",{}).get(name,{}).get("players",[])}
            current_ids = {p["id"] for p in rows}
            value["teams"][name] = {"id":str(team["id"]),"players":rows,"roster_timestamp":roster.get("timestamp"),
                                   "adjustment_ready":ready,"missing_boxscores":len(missing_for_team),
                                   "rotation":projected_rotation(boxes,name,season),
                                   "roster_url":f'https://www.espn.com/wnba/team/roster/_/id/{team["id"]}',
                                   "added_ids":sorted(current_ids-previous_ids) if previous_ids else [],
                                   "removed_ids":sorted(previous_ids-current_ids) if previous_ids else [],
                                   "has_previous_roster":bool(previous_ids)}
        value["apply_adjustments"] = bool(model) and enough_history
        if coverage["missing_games"] and value["apply_adjustments"]:
            value.update(status="partial",message=f"Live reports; {coverage['covered_games']}/{coverage['expected_games']} box scores available. Adjustments are limited to teams with complete current-season player history.")
        if not value["apply_adjustments"]:
            value.update(status="partial",message="Player box-score coverage is incomplete; rosters are shown but score-only forecasts are used.")
    except Exception as error:
        print(f"  Player feed unavailable ({type(error).__name__}: {error}); keeping the score-only baseline",flush=True)
        value.update(status="unavailable",apply_adjustments=False,message="A player feed could not be verified; score-only forecasts are used.")
        if not value["teams"]:
            value["teams"] = previous.get("teams",{})
            value["cached_roster_at"] = previous.get("fetched_at")
    atomic_json(path,value)
    print(f"  Availability: {value['status']}; {len(value['teams'])} teams; adjustments {'enabled' if value['apply_adjustments'] else 'disabled'}",flush=True)
    return value


if __name__ == "__main__":
    refresh()

