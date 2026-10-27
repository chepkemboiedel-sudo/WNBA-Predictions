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
    print(f"Verified forecast through {forecast['data_through']}, {forecast['n_sims']:,} simulations.")


if __name__ == "__main__":
    verify()
