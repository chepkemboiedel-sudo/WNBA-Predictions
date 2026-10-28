"""Select seasons from observed data; never invent a new season's standings."""
from datetime import datetime, timezone


def latest(games):
    return int(games.season.max())


def forecast_season(games):
    for year in sorted(games.season.unique(), reverse=True):
        regular = games[(games.season == year) & ~games.is_playoff]
        counts = regular.home_team.value_counts().add(regular.away_team.value_counts(), fill_value=0)
        if len(counts) >= 8 and counts.min() >= 3:
            return int(year)
    raise ValueError("At least eight teams with three completed regular-season games are required.")


def context(games, now=None):
    year = forecast_season(games)
    calendar = (now or datetime.now(timezone.utc)).year
    return {"season": year, "latest_observed_season": latest(games), "calendar_season": calendar,
            "waiting_for_season": calendar > year or latest(games) > year,
            "format_provisional": year > 2026,
            "message": (f"Showing the {year} forecast until the next season has enough completed games. "
                        if calendar > year or latest(games) > year else "") +
                       ("Future-season bracket uses the last verified eight-team format provisionally; league rule changes require review."
                        if year > 2026 else "Eight-team bracket; observed playoff results are retained.")}

