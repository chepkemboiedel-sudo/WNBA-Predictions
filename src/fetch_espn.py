"""
fetch_espn.py
=============
Download WNBA game logs from ESPN's public JSON API and cache them locally.

Why ESPN and not Kaggle / Basketball-Reference?
    * ESPN's endpoints are public, need no login/API key, and return one
      consistent schema for EVERY season (2016 -> the live 2026 season).
    * Basketball-Reference blocks automated requests (HTTP 403).
    * Kaggle needs credentials and only covers 2015-2024, leaving a gap right
      before the season we care about. ESPN closes that gap with live data.

Two endpoints are combined:
    1. CORE API  -> the authoritative list of games for a given season & round.
       We use it only to learn *which calendar dates* had games.
         https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/
             seasons/{YEAR}/types/{TYPE}/events?limit=1000
       TYPE 2 = regular season, TYPE 3 = playoffs.
    2. SITE SCOREBOARD -> the full box score (teams, points, winner) for one
       calendar day. Reliable for past AND current seasons when queried one
       day at a time.
         https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/
             scoreboard?dates={YYYYMMDD}

The result is one tidy "event-level" table (one row per game) cached to
data/games_{YEAR}.csv, plus a combined data/all_games.csv.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
HEADERS = {"User-Agent": "Mozilla/5.0 (research; personal WNBA analysis)"}
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DATA_DIR = os.path.abspath(DATA_DIR)

CORE_EVENTS = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/"
    "seasons/{year}/types/{stype}/events?limit=1000"
)
SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/"
    "scoreboard?dates={date}&limit=100"
)

# ESPN groups a scoreboard day by U.S. Eastern date. A late West-coast tip-off
# is stored in UTC as the *next* day (e.g. 02:00Z). Shifting UTC back by 6h
# lands every game on its correct Eastern calendar date before we query.
ET_SHIFT_HOURS = 6


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_json(url: str, tries: int = 3, pause: float = 1.0) -> dict | None:
    """GET a URL and parse JSON, retrying a couple of times on transient errors."""
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(pause * (attempt + 1))
    return None


def _game_dates_for_season(year: int) -> list[str]:
    """
    Return every calendar date (YYYYMMDD) in the season window for `year`.

    WNBA regular seasons tip off in May and playoffs finish by late October, so
    May 1 -> Nov 5 safely brackets every season 2016-2026 (including the shifted
    2020 "bubble" season). We simply query the scoreboard for each day; days
    with no games return an empty list and cost one cheap request. This is more
    robust than the core API, whose event list contains only opaque $refs with
    no inline date.
    """
    start = datetime(year, 5, 1)
    end = min(datetime(year, 11, 5), datetime.now(timezone.utc).replace(tzinfo=None))
    days = (end - start).days + 1
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]


def _parse_scoreboard_day(payload: dict, year: int) -> list[dict]:
    """Turn one scoreboard-day JSON blob into a list of event-level game rows."""
    rows: list[dict] = []
    for ev in payload.get("events", []):
        comp = ev["competitions"][0]

        # Only keep completed games that count as real team results.
        if not comp["status"]["type"].get("completed"):
            continue

        season_type = ev.get("season", {}).get("type")  # 2 = regular, 3 = playoff
        if season_type not in (2, 3):  # drop preseason (type 1)
            continue

        # Regular games are tagged "STD"; playoff games use round labels
        # (RD16, QTR, SEMI, FINAL, ...). We keep all of those and drop only the
        # exhibitions that don't represent a normal head-to-head result.
        ctype_abbr = comp.get("type", {}).get("abbreviation")
        if ctype_abbr in ("ALLSTAR", "CC"):  # All-Star game, Commissioner's Cup final
            continue

        # Split the two competitors into home / away.
        home = away = None
        for c in comp["competitors"]:
            if c["homeAway"] == "home":
                home = c
            else:
                away = c
        if home is None or away is None:
            continue
        try:
            hs, as_ = int(home["score"]), int(away["score"])
        except (TypeError, ValueError):
            continue

        rows.append(
            {
                "game_id": ev.get("id"),
                "date": ev["date"][:10],
                "season": year,
                "is_playoff": season_type == 3,
                "home_team": home["team"]["displayName"],
                "home_abbr": home["team"]["abbreviation"],
                "away_team": away["team"]["displayName"],
                "away_abbr": away["team"]["abbreviation"],
                "home_score": hs,
                "away_score": as_,
                "home_win": int(hs > as_),
            }
        )
    return rows


def fetch_season(year: int, force: bool = False) -> pd.DataFrame:
    """
    Fetch (or load from cache) every completed game for one season.

    Set force=True to ignore the cache and re-download — useful for the live
    2026 season, whose results change as new games are played.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    cache = os.path.join(DATA_DIR, f"games_{year}.csv")
    if os.path.exists(cache) and not force:
        return pd.read_csv(cache, parse_dates=["date"])

    dates = sorted(_game_dates_for_season(year))
    print(f"  {year}: {len(dates)} game-days to fetch...")

    rows: list[dict] = []
    failed_dates = []
    # A small thread pool keeps this polite but quick (each day is one request).
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {
            pool.submit(_get_json, SCOREBOARD.format(date=d)): d for d in dates
        }
        for fut in as_completed(futs):
            payload = fut.result()
            if payload is None or "events" not in payload:
                failed_dates.append(futs[fut])
            else:
                rows.extend(_parse_scoreboard_day(payload, year))
    if failed_dates:
        raise RuntimeError(
            f"Could not refresh {year}: {len(failed_dates)} scoreboard requests failed. "
            "Existing cached data has been preserved."
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        # Dedupe (a game can surface under two adjacent day queries) and sort.
        df = df.drop_duplicates("game_id").sort_values("date").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["date"])
        if os.path.exists(cache):
            previous = pd.read_csv(cache)
            if len(df) < len(previous):
                raise RuntimeError(
                    f"Refresh returned fewer games ({len(df)}) than the cache "
                    f"({len(previous)}); refusing to replace it."
                )
        temporary = cache + ".tmp"
        df.to_csv(temporary, index=False)
        os.replace(temporary, cache)
    else:
        raise RuntimeError(f"No completed games returned for {year}; cache preserved.")
    print(f"  {year}: {len(df)} games "
          f"({int(df['is_playoff'].sum()) if not df.empty else 0} playoff)")
    return df


def fetch_all(start: int = 2016, end: int = 2026, refresh_current: bool = True) -> pd.DataFrame:
    """
    Fetch every season in [start, end] and write data/all_games.csv.

    The current (last) season is always re-downloaded so the model runs on the
    freshest standings; earlier seasons are served from cache once fetched.
    """
    frames = []
    for yr in range(start, end + 1):
        force = refresh_current and yr == end
        frames.append(fetch_season(yr, force=force))
    allg = pd.concat(frames, ignore_index=True)
    allg = allg.sort_values("date").reset_index(drop=True)
    out = os.path.join(DATA_DIR, "all_games.csv")
    allg.to_csv(out, index=False)
    print(f"\nTotal: {len(allg)} games, {allg['season'].nunique()} seasons "
          f"({allg['season'].min()}-{allg['season'].max()}) -> {out}")
    return allg


if __name__ == "__main__":
    fetch_all()
