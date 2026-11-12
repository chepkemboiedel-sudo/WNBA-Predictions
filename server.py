#!/usr/bin/env python3
"""
server.py -- Deployable lab service around the WNBA prediction model.

This single, dependency-free (standard-library only) HTTP server wraps the
existing validated per-game win-probability model and adds the operational
features required by the deployment / guardrails lab:

  * Feature 1.1  Public URL          -> serves the real static site in public/
                                        plus a live inference API, so a stranger
                                        can open it and use it with no setup.
  * Feature 1.2  No secrets          -> every setting comes from an environment
                                        variable (see .env.example). Nothing
                                        secret is read from or written to the repo.
  * Feature 1.3  Structured logging  -> one JSON object per line appended to
                                        LOG_PATH for every API request, with a
                                        timestamp, latency, token counts and an
                                        outcome.
  * Feature 2.1  Rate limit          -> an in-memory {client: [timestamps]}
                                        limiter. Over the limit returns HTTP 429
                                        with a clean JSON message.
  * Feature 2.2  Graceful degradation-> any failure (including a deliberately
                                        simulated one) returns a sensible JSON
                                        message and a 503/4xx status, never a
                                        stack trace or a hang.
  * Feature 2.3  Usage summary       -> GET /usage renders request count, p50
                                        and p95 latency and total estimated cost
                                        computed from the log file.

Run locally:   python server.py
Deploy:        any host that can run `python server.py` (Render, Railway,
               Hugging Face Spaces, Cloud Run, ...). Reads $PORT automatically.

NOTE ON TOKENS/COST: this project is a statistics/ML app, not an LLM app, so it
has no real language-model tokens. To satisfy the lab's schema honestly, each
request logs an *estimated* token count derived from the size of the request and
response payloads (~chars / 4), and an estimated cost at PRICE_PER_1K_TOKENS_USD.
These fields are clearly a payload-size proxy, documented in LAB.md -- they are
not fabricated LLM usage.
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import uuid
import warnings
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

warnings.filterwarnings("ignore")  # quiet the sklearn unpickle version notice

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(ROOT, "public")
SRC_DIR = os.path.join(ROOT, "src")


# --------------------------------------------------------------------------- #
# Configuration -- ALL from environment variables, with safe defaults.
# --------------------------------------------------------------------------- #
def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


PORT = _int("PORT", 8000)
HOST = os.environ.get("HOST", "0.0.0.0")
RATE_LIMIT_MAX = _int("RATE_LIMIT_MAX", 30)
RATE_LIMIT_WINDOW_SEC = _int("RATE_LIMIT_WINDOW_SEC", 60)
LOG_PATH = os.environ.get("LOG_PATH", os.path.join(ROOT, "logs", "requests.jsonl"))
PRICE_PER_1K_TOKENS_USD = _float("PRICE_PER_1K_TOKENS_USD", 0.002)
FORCE_FAIL = os.environ.get("FORCE_FAIL", "0") == "1"

_log_lock = threading.Lock()
_rate_lock = threading.Lock()
_rate_state: dict[str, deque] = defaultdict(deque)


# --------------------------------------------------------------------------- #
# Model inference (loaded once at startup; falls back gracefully if it fails)
# --------------------------------------------------------------------------- #
class Inference:
    """Loads the real logistic win-probability model and current team form."""

    def __init__(self) -> None:
        self.ready = False
        self.error: str | None = None
        self.model_version = "score-logistic-v1"
        self._teams: list[str] = []
        self._feats: dict = {}
        self._model = None

    def load(self) -> None:
        try:
            sys.path.insert(0, SRC_DIR)
            import joblib
            import pandas as pd
            from simulate import current_team_features, compute_standings

            games = pd.read_csv(os.path.join(ROOT, "data", "all_games.csv"),
                                parse_dates=["date"])
            bundle = joblib.load(os.path.join(ROOT, "data", "models.joblib"))
            self._model = bundle["logistic"]
            # Feature snapshot for every team in the current season, so any
            # matchup a caller asks for can be scored.
            teams = compute_standings(games)["team"].tolist()
            self._feats = current_team_features(games, teams)
            self._teams = sorted(self._feats.keys())
            self.ready = True
            print(f"[startup] model loaded; {len(self._teams)} teams available")
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the server
            self.error = f"{type(exc).__name__}: {exc}"
            self.ready = False
            print(f"[startup] model load FAILED ({self.error}); "
                  f"API will degrade gracefully")

    def teams(self) -> list[str]:
        return list(self._teams)

    def predict(self, home: str, away: str) -> dict:
        """P(home beats away) with home-court. Raises ValueError on bad input."""
        if not self.ready:
            raise RuntimeError("model unavailable")
        if not home or not away:
            raise ValueError("both 'home' and 'away' team names are required")
        home_t = self._match_team(home)
        away_t = self._match_team(away)
        if home_t is None:
            raise ValueError(f"unknown team: {home!r}")
        if away_t is None:
            raise ValueError(f"unknown team: {away!r}")
        if home_t == away_t:
            raise ValueError("home and away teams must differ")
        from simulate import prob_A_beats_B
        p_home = float(prob_A_beats_B(self._model, self._feats[home_t],
                                      self._feats[away_t], a_home=True))
        return {
            "home_team": home_t,
            "away_team": away_t,
            "p_home_wins": round(p_home, 4),
            "p_away_wins": round(1.0 - p_home, 4),
            "model_version": self.model_version,
        }

    def _match_team(self, name: str) -> str | None:
        name = name.strip()
        for t in self._teams:
            if t.lower() == name.lower():
                return t
        # forgiving substring match ("lynx" -> "Minnesota Lynx")
        hits = [t for t in self._teams if name.lower() in t.lower()]
        return hits[0] if len(hits) == 1 else None


INFER = Inference()


# --------------------------------------------------------------------------- #
# Structured request logging (Feature 1.3)
# --------------------------------------------------------------------------- #
def approx_tokens(text: str) -> int:
    """Rough token estimate from payload size (~4 chars/token). Documented as a
    payload-size proxy -- this app has no real LLM tokens."""
    return max(1, math.ceil(len(text or "") / 4))


def write_log(entry: dict) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    line = json.dumps(entry, separators=(",", ":"))
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------- #
# Rate limiting (Feature 2.1) -- in-memory {client: [timestamps]}
# --------------------------------------------------------------------------- #
def rate_check(client: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds). Sliding window over WINDOW_SEC."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SEC
    with _rate_lock:
        hits = _rate_state[client]
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= RATE_LIMIT_MAX:
            retry = int(math.ceil(hits[0] + RATE_LIMIT_WINDOW_SEC - now))
            return False, max(retry, 1)
        hits.append(now)
        return True, 0


# --------------------------------------------------------------------------- #
# Usage summary (Feature 2.3) -- computed from the log file
# --------------------------------------------------------------------------- #
def percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def usage_summary() -> dict:
    entries: list[dict] = []
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    latencies = sorted(e.get("latency_ms", 0.0) for e in entries)
    outcomes: dict[str, int] = defaultdict(int)
    total_tokens = 0
    total_cost = 0.0
    for e in entries:
        outcomes[e.get("outcome", "unknown")] += 1
        total_tokens += int(e.get("total_tokens", 0) or 0)
        total_cost += float(e.get("est_cost_usd", 0.0) or 0.0)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "log_path": os.path.relpath(LOG_PATH, ROOT),
        "request_count": len(entries),
        "outcomes": dict(outcomes),
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 1),
            "p95": round(percentile(latencies, 0.95), 1),
            "max": round(latencies[-1], 1) if latencies else 0.0,
        },
        "total_tokens": total_tokens,
        "price_per_1k_tokens_usd": PRICE_PER_1K_TOKENS_USD,
        "total_estimated_cost_usd": round(total_cost, 6),
    }


def usage_html(summary: dict) -> str:
    rows = "".join(
        f"<tr><td>{k}</td><td style='text-align:right'>{v}</td></tr>"
        for k, v in summary["outcomes"].items()
    )
    lat = summary["latency_ms"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Usage summary - WNBA prediction service</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto;
          padding: 0 1rem; color: #16181d; }}
  h1 {{ font-size: 1.3rem; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; margin: 1rem 0; }}
  .card {{ border: 1px solid #e3e6ea; border-radius: 10px; padding: .9rem 1rem; }}
  .card .n {{ font-size: 1.6rem; font-weight: 650; }}
  .card .k {{ color: #5b6672; font-size: .8rem; text-transform: uppercase;
             letter-spacing: .04em; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; }}
  td {{ border-top: 1px solid #eee; padding: .35rem .2rem; }}
  .muted {{ color: #5b6672; font-size: .85rem; }}
  code {{ background: #f3f4f6; padding: .1rem .35rem; border-radius: 5px; }}
</style></head><body>
<h1>Usage summary</h1>
<p class="muted">Generated {summary['generated_at']} from <code>{summary['log_path']}</code>.</p>
<div class="grid">
  <div class="card"><div class="k">Requests</div><div class="n">{summary['request_count']}</div></div>
  <div class="card"><div class="k">p50 latency</div><div class="n">{lat['p50']} ms</div></div>
  <div class="card"><div class="k">p95 latency</div><div class="n">{lat['p95']} ms</div></div>
  <div class="card"><div class="k">Est. total cost</div><div class="n">${summary['total_estimated_cost_usd']}</div></div>
</div>
<h2 style="font-size:1rem">Outcomes</h2>
<table>{rows or '<tr><td class="muted">no requests logged yet</td><td></td></tr>'}</table>
<p class="muted">Max latency {lat['max']} ms &middot; {summary['total_tokens']} estimated tokens
&middot; priced at ${summary['price_per_1k_tokens_usd']}/1k tokens (payload-size proxy; see LAB.md).</p>
<p class="muted"><a href="/usage.json">usage.json</a> &middot; <a href="/">back to app</a></p>
</body></html>"""


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css",
    ".js": "application/javascript", ".json": "application/json",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "wnba-lab/1.0"
    protocol_version = "HTTP/1.1"

    # Silence the default noisy stderr logging; we do our own structured logs.
    def log_message(self, *args) -> None:  # noqa: D401
        return

    def _client_id(self) -> str:
        # Allow an explicit per-user header for demos; fall back to source IP.
        return (self.headers.get("X-User")
                or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def _send_json(self, status: int, payload: dict) -> bytes:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
        return body

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path in ("/api/predict", "/api/forecast", "/api/teams"):
            self._handle_api(path, query)
            return
        if path == "/usage":
            self._send_html(200, usage_html(usage_summary()))
            return
        if path == "/usage.json":
            self._send_json(200, usage_summary())
            return
        if path == "/healthz":
            self._send_json(200, {"status": "ok", "model_ready": INFER.ready})
            return
        self._serve_static(path)

    # ---- API endpoints: logged, rate-limited, degrade gracefully ---------- #
    def _handle_api(self, path: str, query: dict) -> None:
        start = time.perf_counter()
        client = self._client_id()
        req_descriptor = f"{path}?{json.dumps(query, sort_keys=True)}"
        status = 200
        outcome = "ok"
        body = b""

        # Rate limit first -- a blocked request is still logged.
        allowed, retry_after = rate_check(client)
        if not allowed:
            status, outcome = 429, "rate_limited"
            body = self._send_json(status, {
                "error": "Rate limit exceeded. Please slow down and retry.",
                "limit": RATE_LIMIT_MAX,
                "window_seconds": RATE_LIMIT_WINDOW_SEC,
                "retry_after_seconds": retry_after,
            })
        else:
            try:
                # Deliberate-failure switch for the degradation demo (2.2).
                if FORCE_FAIL or query.get("simulate") == "fail":
                    raise RuntimeError("simulated upstream failure")

                if path == "/api/teams":
                    payload = {"teams": INFER.teams(), "count": len(INFER.teams())}
                elif path == "/api/forecast":
                    payload = self._read_forecast()
                else:  # /api/predict
                    payload = INFER.predict(query.get("home", ""),
                                            query.get("away", ""))
                body = self._send_json(status, payload)

            except ValueError as exc:
                status, outcome = 400, "bad_request"
                body = self._send_json(status, {
                    "error": "Invalid request.",
                    "detail": str(exc),
                    "hint": "GET /api/teams lists valid team names.",
                })
            except Exception as exc:  # noqa: BLE001 - graceful degradation (2.2)
                status, outcome = 503, "degraded"
                body = self._send_json(status, {
                    "error": "Prediction service is temporarily unavailable. "
                             "Please try again shortly.",
                })
                # The real reason stays server-side, out of the user's response.
                print(f"[degraded] {path} -> {type(exc).__name__}: {exc}")

        latency_ms = (time.perf_counter() - start) * 1000.0
        prompt_tokens = approx_tokens(req_descriptor)
        completion_tokens = approx_tokens(body.decode("utf-8", "ignore"))
        total_tokens = prompt_tokens + completion_tokens
        write_log({
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "request_id": uuid.uuid4().hex[:12],
            "client": client,
            "method": "GET",
            "path": path,
            "query": query,
            "status": status,
            "outcome": outcome,
            "latency_ms": round(latency_ms, 2),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "est_cost_usd": round(total_tokens / 1000.0 * PRICE_PER_1K_TOKENS_USD, 6),
            "model_version": INFER.model_version,
        })

    def _read_forecast(self) -> dict:
        path = os.path.join(ROOT, "outputs", "forecast.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ---- Static site (keeps the real public/ app reachable) --------------- #
    def _serve_static(self, path: str) -> None:
        rel = unquote(path.lstrip("/")) or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        full = os.path.normpath(os.path.join(PUBLIC_DIR, rel))
        if not full.startswith(PUBLIC_DIR) or not os.path.isfile(full):
            # directory index fallback (e.g. /teams/atlanta-dream/)
            idx = os.path.join(full, "index.html")
            if os.path.isdir(full) and os.path.isfile(idx):
                full = idx
            else:
                self._send_json(404, {"error": "Not found", "path": path})
                return
        ext = os.path.splitext(full)[1].lower()
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            self._send_json(404, {"error": "Not found", "path": path})
            return
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    print(f"[startup] loading model (one-time, ~30s)...")
    INFER.load()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[startup] serving on http://{HOST}:{PORT}  "
          f"(rate limit {RATE_LIMIT_MAX}/{RATE_LIMIT_WINDOW_SEC}s, "
          f"logs -> {os.path.relpath(LOG_PATH, ROOT)})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[shutdown] bye")
        httpd.server_close()


if __name__ == "__main__":
    main()
