#!/usr/bin/env python3
"""
generate_traffic.py -- drive real traffic at the running lab server so the log
file fills with genuine entries and the guardrails can be demonstrated.

It produces:
  * a spread of successful /api/predict and /api/forecast calls (varied latency),
  * a couple of bad requests (unknown team) -> logged as bad_request,
  * one simulated failure (?simulate=fail)  -> logged as degraded,
  * a rapid burst from a single user to TRIP the rate limit -> logged as
    rate_limited (HTTP 429).

Usage:
    python scripts/generate_traffic.py                 # default http://localhost:8000
    python scripts/generate_traffic.py --base URL --burst 40

No third-party dependencies -- standard library only.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

MATCHUPS = [
    ("Minnesota Lynx", "New York Liberty"),
    ("Las Vegas Aces", "Indiana Fever"),
    ("Golden State Valkyries", "Dallas Wings"),
    ("Atlanta Dream", "Washington Mystics"),
    ("New York Liberty", "Atlanta Dream"),
    ("Las Vegas Aces", "Golden State Valkyries"),
    ("Indiana Fever", "Minnesota Lynx"),
    ("Washington Mystics", "Dallas Wings"),
]


def call(base: str, path: str, user: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(base.rstrip("/") + path)
    if user:
        req.add_header("X-User", user)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore")
    except urllib.error.URLError as exc:
        print(f"  ! could not reach {base} ({exc.reason}). Is the server running?")
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--burst", type=int, default=40,
                    help="rapid requests from one user to trip the rate limit")
    args = ap.parse_args()

    print(f"Target: {args.base}")

    print("\n1) Normal inference traffic (varied users)...")
    ok = 0
    for i, (home, away) in enumerate(MATCHUPS):
        status, body = call(args.base, f"/api/predict?home={urlquote(home)}&away={urlquote(away)}",
                            user=f"viewer-{i % 3}")
        ok += status == 200
        if status == 200:
            d = json.loads(body)
            print(f"   {d['home_team']} vs {d['away_team']}: "
                  f"{d['p_home_wins']:.0%} / {d['p_away_wins']:.0%}")
        time.sleep(0.1)
    for i in range(4):
        call(args.base, "/api/forecast", user=f"viewer-{i % 3}")
    print(f"   {ok} predictions + 4 forecast calls OK")

    print("\n2) Bad requests (unknown team) -> expect 400 bad_request...")
    for bad in ("Atlantis Dream", "Narnia Lions"):
        status, _ = call(args.base, f"/api/predict?home={urlquote(bad)}&away=Minnesota%20Lynx")
        print(f"   {bad}: HTTP {status}")

    print("\n3) Simulated failure (?simulate=fail) -> expect 503 degraded...")
    status, body = call(args.base, "/api/predict?home=Minnesota%20Lynx&away=Atlanta%20Dream&simulate=fail")
    print(f"   HTTP {status}: {json.loads(body).get('error')}")

    print(f"\n4) Rate-limit burst: {args.burst} CONCURRENT calls from ONE user...")
    # Fire concurrently so every request lands inside the limiter's window --
    # a realistic load spike. (Sequential calls on Windows can spread wide
    # enough that a sliding window never fills; a burst is what trips a limit.)
    import concurrent.futures as cf

    def one(_n: int) -> int:
        status, _ = call(args.base,
                         "/api/predict?home=Las%20Vegas%20Aces&away=Indiana%20Fever",
                         user="burst-user")
        return status

    with cf.ThreadPoolExecutor(max_workers=min(args.burst, 25)) as pool:
        statuses = list(pool.map(one, range(args.burst)))
    allowed = sum(s == 200 for s in statuses)
    blocked = sum(s == 429 for s in statuses)
    if blocked:
        print(f"   {allowed} allowed, {blocked} blocked with HTTP 429. "
              f"Rate limit demonstrated.")
    else:
        print("   no 429 seen -- raise --burst or lower RATE_LIMIT_MAX on the server.")

    print("\nDone. View the summary at", args.base.rstrip("/") + "/usage")
    print("or run:  python scripts/usage_report.py")


def urlquote(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


if __name__ == "__main__":
    main()
