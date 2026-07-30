"""
compare_odds.py
===============
Sanity-check the model's championship probabilities against real sportsbook
futures (ESPN BET, pulled live from ESPN's public odds endpoint).

American odds are converted to implied probabilities and then de-vigged
(normalized to sum to 1) so they are directly comparable to the model's
probabilities. Books build in a margin -- here the raw implied probabilities
summed to ~1.29, i.e. a 29% overround -- which we divide out.
"""

from __future__ import annotations

import os

import matplotlib.pyplot as plt
import pandas as pd
import requests

HERE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))
OUT = os.path.abspath(os.path.join(HERE, "..", "outputs"))
HDR = {"User-Agent": "Mozilla/5.0"}


def _american_to_implied(value: str) -> float:
    a = int(str(value).replace("+", ""))
    return 100 / (a + 100) if a > 0 else abs(a) / (abs(a) + 100)


def fetch_market_odds(season: int = 2026) -> pd.DataFrame:
    """Live ESPN BET championship futures, de-vigged. Falls back to cache."""
    cache = os.path.join(DATA, "market_odds.csv")
    try:
        teams = requests.get(
            f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/"
            f"seasons/{season}/teams?limit=50", headers=HDR, timeout=20).json()
        idname = {}
        for it in teams["items"]:
            t = requests.get(it["$ref"], headers=HDR, timeout=20).json()
            idname[str(t["id"])] = t.get("displayName")
        fut = requests.get(
            f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/"
            f"seasons/{season}/futures?limit=50", headers=HDR, timeout=20).json()
        books = fut["items"][0]["futures"][0]["books"]  # ESPN BET
        rows = []
        for b in books:
            tid = b["team"]["$ref"].split("/teams/")[-1].split("?")[0]
            rows.append({"team": idname.get(tid, tid), "american": b["value"],
                         "implied_raw": _american_to_implied(b["value"])})
        df = pd.DataFrame(rows)
        df["market_novig"] = df.implied_raw / df.implied_raw.sum()
        df.to_csv(cache, index=False)
        return df
    except Exception as e:  # network hiccup -> use last saved snapshot
        print(f"  (live odds fetch failed: {e}; using cache)")
        return pd.read_csv(cache)


def compare(out_path: str):
    model = pd.read_csv(os.path.join(OUT, "finals_probabilities.csv"))
    market = fetch_market_odds()
    df = model.merge(market[["team", "market_novig"]], on="team", how="left")
    df["market_novig"] = df["market_novig"].fillna(0.0)
    df = df.sort_values("p_champion", ascending=True)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    y = range(len(df))
    ax.barh([i + 0.2 for i in y], df.p_champion * 100, height=0.4,
            color="#1f77b4", label="Model (simulation)")
    ax.barh([i - 0.2 for i in y], df.market_novig * 100, height=0.4,
            color="#ff7f0e", label="Market (ESPN BET, de-vigged)")
    ax.set_yticks(list(y))
    ax.set_yticklabels([f"({s}) {t}" for s, t in zip(df.seed, df.team)])
    ax.set_xlabel("Championship probability (%)")
    ax.set_title("Model vs. sportsbook — 2026 WNBA title odds")
    ax.legend()
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)

    print("\nModel vs market championship probability:")
    print(f"  {'Team':<24}{'Model':>8}{'Market':>9}{'Diff':>8}")
    for _, r in df.sort_values("p_champion", ascending=False).iterrows():
        print(f"  {r.team:<24}{r.p_champion:>7.1%}{r.market_novig:>9.1%}"
              f"{(r.p_champion - r.market_novig):>+8.1%}")
    print(f"\nComparison chart -> {out_path}")
    return df


if __name__ == "__main__":
    compare(os.path.join(OUT, "model_vs_market.png"))
