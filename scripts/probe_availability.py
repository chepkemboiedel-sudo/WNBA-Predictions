"""Inspect public ESPN availability schemas without exposing local credentials."""
import json
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parents[1] / "data" / "availability_probe"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"


def get(name, url):
    response = requests.get(url, timeout=25)
    response.raise_for_status()
    payload = response.json()
    (OUT / (name + ".json")).write_text(json.dumps(payload), encoding="utf-8")
    return payload


teams = get("teams", BASE + "/teams?limit=100")["sports"][0]["leagues"][0]["teams"]
for item in teams:
    team = item["team"]
    print(team["id"], team["displayName"])
    if team["displayName"] in ("Golden State Valkyries", "Atlanta Dream"):
        roster = get("roster_" + team["id"], BASE + f'/teams/{team["id"]}/roster?season=2026')
        print("ROSTER", team["displayName"], list(roster), "athletes", len(roster.get("athletes", [])))
        print("ATHLETE", json.dumps(roster.get("athletes", [])[:1])[:5000])
injuries = get("injuries", BASE + "/injuries?limit=1000")
print("INJURY KEYS", list(injuries))
print("INJURY SAMPLE", json.dumps(injuries)[:6500])
summary = get("summary", BASE + "/summary?event=401918309")
print("SUMMARY KEYS", list(summary))
print("BOX SCORE SAMPLE", json.dumps(summary.get("boxscore", {}).get("players", [])[:1])[:6000])
