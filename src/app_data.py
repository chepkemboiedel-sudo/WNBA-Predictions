"""Published forecast history, team profiles, and refresh-health metadata."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def slug(team: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", team.lower()).strip("-")


def snapshot(results: pd.DataFrame, forecast: dict, meta: dict, *, source="published") -> dict:
    teams = [{"team": row.team, "seed": int(row.seed),
              "reach_finals": float(row.p_reach_finals), "champion": float(row.p_champion)}
             for row in results.sort_values("seed").itertuples()]
    identity = json.dumps([meta.get("last_updated"), forecast["data_through"], teams], sort_keys=True)
    return {"id": hashlib.sha256(identity.encode()).hexdigest()[:16],
            "generated_at": meta.get("last_updated"), "data_through": forecast["data_through"],
            "source": source, "season":forecast.get("season",int(forecast["data_through"][:4])), "n_sims": forecast["n_sims"], "teams": teams,
            "run_url": meta.get("run_url"), "probability_model":forecast.get("probability_model","score-only"),
            "availability_fetched_at":forecast.get("availability",{}).get("fetched_at")}


def append_snapshot(history: dict, entry: dict) -> dict:
    if history.get("version", 1) != 1:
        raise ValueError("Unknown forecast-history format; refusing to replace it.")
    entries = list(history.get("snapshots", []))
    if not any(row["id"] == entry["id"] for row in entries):
        entries.append(entry)
    entries.sort(key=lambda row: row.get("generated_at") or row["data_through"])
    return {"version": 1, "snapshots": entries}


def load_history(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "snapshots": []}


def workflow_url() -> str | None:
    repository, run = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_RUN_ID")
    return f"https://github.com/{repository}/actions/runs/{run}" if repository and run else None


def successful_health(games: pd.DataFrame, forecast: dict, meta: dict, *, verified=True) -> dict:
    current = games[games.season == forecast.get("season",int(games.season.max()))]
    return {"version": 1, "status": "ok", "last_attempt_at": meta["last_updated"],
            "last_success_at": meta["last_updated"], "next_refresh_at": meta["next_refresh_at"],
            "data_through": forecast["data_through"], "season": forecast.get("season",int(games.season.max())),
            "coverage": {"season_games": len(current), "regular_games": int((~current.is_playoff).sum()),
                         "playoff_games": int(current.is_playoff.sum()), "historical_games": len(games)},
            "source": "ESPN completed game results", "verified": verified,
            "run_url": meta.get("run_url"), "availability":forecast.get("availability"),
            "message": "Last forecast refresh completed successfully."}


def failed_health(previous: dict, *, now: datetime | None = None, run_url: str | None = None) -> dict:
    value = dict(previous)
    value.update(version=1, status="failed",
                 last_attempt_at=(now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
                 run_url=run_url,
                 message="The latest cloud refresh failed. The last published forecast is still available.")
    return value


def team_profiles(games: pd.DataFrame, results: pd.DataFrame, seeds: list[str], season=None) -> list[dict]:
    current = games[games.season == (season or int(games.season.max()))].sort_values(["date", "game_id"], kind="stable")
    profiles = []
    probabilities = results.set_index("team").to_dict("index")
    for team in sorted(set(current.home_team) | set(current.away_team)):
        rows = []
        for row in current[(current.home_team == team) | (current.away_team == team)].itertuples():
            home = row.home_team == team
            pf, pa = (row.home_score, row.away_score) if home else (row.away_score, row.home_score)
            rows.append({"date": str(row.date)[:10], "opponent": row.away_team if home else row.home_team,
                         "opponent_slug": slug(row.away_team if home else row.home_team),
                         "home": home, "playoff": bool(row.is_playoff), "pf": int(pf), "pa": int(pa),
                         "won": bool(pf > pa)})
        regular = [row for row in rows if not row["playoff"]]
        playoffs = [row for row in rows if row["playoff"]]

        def record(group):
            wins = sum(row["won"] for row in group)
            return {"wins": wins, "losses": len(group) - wins}

        opponents = []
        for opponent in sorted({row["opponent"] for row in regular}):
            played = [row for row in regular if row["opponent"] == opponent]
            opponents.append({"team": opponent, "slug": slug(opponent), **record(played),
                              "margin": round(sum(row["pf"] - row["pa"] for row in played) / len(played), 1)})
        latest = rows[-1]["won"]
        streak = 0
        for row in reversed(rows):
            if row["won"] != latest:
                break
            streak += 1
        probability = probabilities.get(team)
        profiles.append({"team": team, "slug": slug(team), "seed": seeds.index(team) + 1 if team in seeds else None,
                         "regular": record(regular), "playoffs": record(playoffs),
                         "home": record([row for row in regular if row["home"]]),
                         "away": record([row for row in regular if not row["home"]]),
                         "last10": record(regular[-10:]), "streak": ("W" if latest else "L") + str(streak),
                         "points_for": round(sum(row["pf"] for row in regular) / len(regular), 1),
                         "points_against": round(sum(row["pa"] for row in regular) / len(regular), 1),
                         "point_diff": round(sum(row["pf"] - row["pa"] for row in regular) / len(regular), 1),
                         "probabilities": {"reach_finals": probability["p_reach_finals"],
                                           "champion": probability["p_champion"],
                                           "champion_baseline":probability.get("p_champion_baseline",probability["p_champion"])} if probability else None,
                         "recent": list(reversed(rows[-10:])), "head_to_head": opponents})
    return profiles

