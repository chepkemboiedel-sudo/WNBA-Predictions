# Deployment & Guardrails Lab — WNBA Prediction Service

This document maps every lab feature to exactly what to show, and gives
copy-paste commands for the demo video. The lab is applied to my final
project (the WNBA 2026 Finals prediction model), which is **encouraged** per
the brief.

> **One honest caveat, stated up front (also in the video):** this project is a
> *statistics / machine-learning* app, not an LLM app. It calls a logistic
> win-probability model, not a language model, so it has **no real LLM tokens or
> per-token cost**. To satisfy the lab's logging schema honestly, each request
> logs an *estimated* token count derived from request/response **payload size**
> (~chars ÷ 4) and an estimated cost at a configurable price. These fields are a
> clearly-labelled payload-size proxy — not fabricated LLM usage. Everything else
> (latency, outcome, rate limiting, degradation) is fully real.

---

## The service

[`server.py`](server.py) is a dependency-free (standard-library only) HTTP
server that wraps the existing validated model and adds all six operational
features. It serves:

| Route | Purpose |
|---|---|
| `GET /` and the rest of `public/` | the real static prediction site |
| `GET /api/predict?home=<team>&away=<team>` | live model inference → win probability |
| `GET /api/forecast` | the current Monte-Carlo Finals forecast |
| `GET /api/teams` | valid team names |
| `GET /usage` | human-readable usage summary (Feature 2.3) |
| `GET /usage.json` | same summary as JSON |
| `GET /healthz` | liveness check |

### Run it locally

```bash
python server.py
```

First boot loads the model once (~30s), then prints the listen address. In a
second terminal, generate real traffic:

```bash
python scripts/generate_traffic.py
```

Then open <http://localhost:8000/usage> or run:

```bash
python scripts/usage_report.py
```

---

## Challenge #1 — Deploy

### Feature 1.1 — Reachable at a public URL by someone who isn't me

Two independent public deployments already exist / are supported:

- **Static site** — the `public/` directory is published on **Vercel** (the
  existing integration), reachable with no setup.
- **Full service** (`server.py`, with the live API + guardrails) deploys to any
  host that runs `python server.py`. A [`Procfile`](Procfile) is included, so on
  **Render / Railway** it is a one-click "new web service from repo": no build
  command needed, the platform injects `$PORT`. Free tier is sufficient.

**Show in video:** open the deployed URL in a browser the instructor could use;
click a matchup / hit `/api/predict`; show it responding with no login.

### Feature 1.2 — No secrets in the repository

- The app requires **no API keys at all** — ESPN's feeds are public and keyless,
  and the GitHub Actions workflows use GitHub's built-in token, not a PAT.
- All server configuration comes from **environment variables**
  ([`.env.example`](.env.example) documents them); real values live in the host's
  env UI or a git-ignored `.env`.
- [`.gitignore`](.gitignore) excludes `.env` and `logs/`.

**Show in video — prove a fresh clone has no credentials:**

```bash
git clone <repo-url> fresh-clone && cd fresh-clone
git grep -niE "api[_-]?key|secret|password|bearer|sk-[A-Za-z0-9]{20}"
```

The only hit is a README sentence saying *no* personal access token is needed.
Then show `.env.example` (placeholders only) and that `.env` is git-ignored.

### Feature 1.3 — Structured request logging (≥20 real entries)

Every API request appends one JSON object per line to `logs/requests.jsonl`
(`LOG_PATH`). Each entry contains **timestamp, latency, token counts, and
outcome**, plus client, path, status, and model version:

```json
{"ts":"2026-11-12T18:03:11Z","request_id":"a1b2c3d4e5f6","client":"viewer-0","method":"GET","path":"/api/predict","query":{"home":"Minnesota Lynx","away":"New York Liberty"},"status":200,"outcome":"ok","latency_ms":41.7,"prompt_tokens":18,"completion_tokens":44,"total_tokens":62,"est_cost_usd":0.000124,"model_version":"score-logistic-v1"}
```

**Show in video:** run `generate_traffic.py` (produces 50+ entries), then
`tail -n 25 logs/requests.jsonl` to show ≥20 real entries from actual use.

---

## Challenge #2 — Guardrails and Operations

### Feature 2.1 — A rate limit that actually triggers

In-memory sliding-window limiter: `{client: [timestamps]}`, keyed by the
`X-User` header (or source IP), `RATE_LIMIT_MAX` requests per
`RATE_LIMIT_WINDOW_SEC`. Over the limit → **HTTP 429** with a clean JSON body;
the blocked request is still logged as `outcome:"rate_limited"`.

**Show in video:** `generate_traffic.py` fires a 40-request burst from one user
and prints the request number where the first 429 appears. Or manually:

```bash
for i in $(seq 1 40); do \
  curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-User: demo" "http://localhost:8000/api/predict?home=Las%20Vegas%20Aces&away=Indiana%20Fever"; \
done
```

You'll see `200`s flip to `429`s once the limit is hit.

### Feature 2.2 — Graceful degradation

Any failure is caught and returned as a sensible JSON message with a 503 —
never a stack trace or a hang. The real cause is logged server-side only.
Two ways to trigger it deliberately (no real outage needed):

```bash
# Per-request switch:
curl -s "http://localhost:8000/api/predict?home=Minnesota%20Lynx&away=Atlanta%20Dream&simulate=fail"
# -> {"error":"Prediction service is temporarily unavailable. Please try again shortly."}

# Whole-service switch (simulates a dead backend):
FORCE_FAIL=1 python server.py
```

A bad request (unknown team) is handled just as cleanly with a 400 and a hint.
The upstream ESPN proxy in [`api/live.js`](api/live.js) already does the same for
the static site: it returns an explicit "unavailable" message on any source
failure.

### Feature 2.3 — Usage summary from my own logs

`GET /usage` (and `scripts/usage_report.py`) read `logs/requests.jsonl` and
report **request count, p50 and p95 latency, outcome breakdown, and total
estimated cost** for the logged period. p95 is computed by sorting latencies and
interpolating the 95th percentile.

**Show in video:** after generating traffic, open `/usage` (the card view) and/or
run `python scripts/usage_report.py` for the printed report.

---

## Feature → file quick reference

| Feature | Where |
|---|---|
| 1.1 Public URL | Vercel (`public/`) + [`Procfile`](Procfile) / [`server.py`](server.py) on Render/Railway |
| 1.2 No secrets | [`.env.example`](.env.example), [`.gitignore`](.gitignore), env-var config in `server.py` |
| 1.3 Structured logging | `write_log()` in [`server.py`](server.py) → `logs/requests.jsonl` |
| 2.1 Rate limit | `rate_check()` in [`server.py`](server.py) |
| 2.2 Graceful degradation | `_handle_api()` try/except in [`server.py`](server.py); `?simulate=fail` / `FORCE_FAIL` |
| 2.3 Usage summary | `/usage` + `usage_summary()` in [`server.py`](server.py); [`scripts/usage_report.py`](scripts/usage_report.py) |
| Traffic for the demo | [`scripts/generate_traffic.py`](scripts/generate_traffic.py) |
