#!/usr/bin/env python3
"""
usage_report.py -- print a usage summary from the structured request log.

A plain-text version of what GET /usage renders, for the lab's "printed report"
(Challenge 2, Feature 3): request count, p50 / p95 latency, outcome breakdown,
and total estimated cost over the logged period.

Usage:
    python scripts/usage_report.py                       # default logs/requests.jsonl
    LOG_PATH=/path/to/requests.jsonl python scripts/usage_report.py
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.environ.get("LOG_PATH", os.path.join(ROOT, "logs", "requests.jsonl"))
PRICE_PER_1K = float(os.environ.get("PRICE_PER_1K_TOKENS_USD", "0.002"))


def percentile(vals: list[float], pct: float) -> float:
    if not vals:
        return 0.0
    vals = sorted(vals)
    k = (len(vals) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return vals[int(k)]
    return vals[lo] * (hi - k) + vals[hi] * (k - lo)


def main() -> None:
    if not os.path.exists(LOG_PATH):
        print(f"No log file at {LOG_PATH}. Start the server and send some traffic first.")
        raise SystemExit(1)

    entries = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if not entries:
        print("Log file is empty.")
        raise SystemExit(1)

    latencies = [e.get("latency_ms", 0.0) for e in entries]
    outcomes = defaultdict(int)
    total_tokens = total_cost = 0
    for e in entries:
        outcomes[e.get("outcome", "unknown")] += 1
        total_tokens += int(e.get("total_tokens", 0) or 0)
        total_cost += float(e.get("est_cost_usd", 0.0) or 0.0)

    span = f"{entries[0].get('ts', '?')}  ->  {entries[-1].get('ts', '?')}"
    print("=" * 56)
    print("  WNBA prediction service -- usage summary")
    print("=" * 56)
    print(f"  Log file        : {os.path.relpath(LOG_PATH, ROOT)}")
    print(f"  Period          : {span}")
    print(f"  Total requests  : {len(entries)}")
    print("  Outcomes        :")
    for k, v in sorted(outcomes.items(), key=lambda kv: -kv[1]):
        print(f"      {k:<14} {v}")
    print("  Latency (ms)    :")
    print(f"      p50  {percentile(latencies, 0.50):8.1f}")
    print(f"      p95  {percentile(latencies, 0.95):8.1f}")
    print(f"      max  {max(latencies):8.1f}")
    print(f"  Est. tokens     : {total_tokens:,}")
    print(f"  Price / 1k tok  : ${PRICE_PER_1K}")
    print(f"  Est. total cost : ${total_cost:.6f}")
    print("=" * 56)
    print("  (tokens/cost are a documented payload-size proxy; see LAB.md)")


if __name__ == "__main__":
    main()
