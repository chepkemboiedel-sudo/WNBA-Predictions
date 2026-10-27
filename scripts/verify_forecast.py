"""Reject an inconsistent forecast before publishing any refreshed artifacts."""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def verify():
    forecast = json.loads((ROOT / "outputs/forecast.json").read_text(encoding="utf-8"))
    meta = json.loads((ROOT / "public/refresh_meta.json").read_text(encoding="utf-8"))
    page = (ROOT / "public/index.html").read_text(encoding="utf-8")
    match = re.search(r"window\.__WNBA__=(.*?);</script>", page)
    if match is None:
        raise ValueError("Website is missing its forecast data.")
    embedded = json.loads(match[1])
    if embedded["refresh"] != meta:
        raise ValueError("Page and refresh metadata disagree.")
    if embedded["observed"] != forecast["observed_series"]:
        raise ValueError("Interactive bracket is using different completed results.")
    if forecast["data_through"] not in page:
        raise ValueError("Page does not show the latest completed game date.")
    results = pd.read_csv(ROOT / "outputs/finals_probabilities.csv")
    if not ((results.p_champion >= 0) & (results.p_champion <= results.p_reach_finals)
            & (results.p_reach_finals <= 1)).all():
        raise ValueError("Invalid championship or Finals probabilities.")
    if abs(results.p_champion.sum() - 1) > 1e-8 or abs(results.p_reach_finals.sum() - 2) > 1e-8:
        raise ValueError("Forecast probabilities do not sum correctly.")
    if results.sort_values("seed").team.tolist() != embedded["seeds"]:
        raise ValueError("Website and simulation seeds disagree.")
    if "p_champion_baseline" in results and abs(results.p_champion_baseline.sum()-1)>1e-8:
        raise ValueError("Score-only comparison probabilities do not sum correctly.")
    availability_path=ROOT/"data/player_availability.json"
    if availability_path.exists():
        availability=json.loads(availability_path.read_text(encoding="utf-8"))
        if embedded.get("availability",{}).get("fetched_at")!=availability.get("fetched_at"):
            raise ValueError("Website is using a different player-data snapshot.")
        for team in availability.get("teams",{}).values():
            if not team.get("adjustment_ready") and any(p.get("extra_absence_points",0)>0 for p in team.get("players",[])):
                raise ValueError("An incomplete team player archive received an adjustment.")
    history = json.loads((ROOT / "data/forecast_history.json").read_text(encoding="utf-8"))
    health = json.loads((ROOT / "public/refresh_health.json").read_text(encoding="utf-8"))
    if embedded["history"] != history or embedded["health"] != health:
        raise ValueError("Page history or refresh health does not match published assets.")
    latest = history["snapshots"][-1]
    if latest["generated_at"] != meta["last_updated"] or health["last_success_at"] != meta["last_updated"]:
        raise ValueError("Forecast history and health do not describe this successful run.")
    if len(list((ROOT / "public/teams").glob("*/index.html"))) != len(set(pd.read_csv(ROOT / "data/games_2026.csv").home_team)):
        raise ValueError("A team detail page is missing.")
    print(f"Verified forecast through {forecast['data_through']}, {forecast['n_sims']:,} simulations.")


if __name__ == "__main__":
    verify()
