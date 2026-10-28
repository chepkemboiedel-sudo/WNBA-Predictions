# WNBA 2026 Finals Prediction

Estimates, with defensible probabilities, which two teams meet in the 2026 WNBA Finals —
by simulating the league's **actual** 8-team, 3-round playoff bracket (best-of-3 →
best-of-5 → best-of-7, no conference brackets, no reseeding) from a validated per-game
win-probability model.

**→ Read [`SUMMARY.md`](SUMMARY.md) for the results and interpretation.**

## Quick start

```bash
pip install -r requirements.txt
python run_all.py
```

That runs the whole pipeline, writes every chart + CSV to `outputs/`, refreshes `SUMMARY.md`,
and rebuilds the website in `public/` and `site/`. The first run
downloads ~11 seasons from ESPN (a few minutes); afterwards historical seasons are cached
and only the live 2026 season is refreshed. Use `python run_all.py --refresh` to force a
full re-download, or `--sims 50000` for more simulations.
Use `python run_all.py --skip-fetch` to rebuild from an already refreshed local game cache.

The **Daily WNBA refresh** GitHub Actions workflow runs the pipeline in the cloud every day
at **7:00 a.m. America/Los_Angeles**, following Pacific daylight saving time. It does not
require your computer or Codex to be running. Successful refreshes commit the generated
artifacts to `main`; the existing Vercel integration publishes the updated `public/` directory.
The workflow checks Vercel's deployment result and reports failures in GitHub Actions.
GitHub may start scheduled jobs later than their target time.

Use the online Vercel app to see cloud updates. `http://127.0.0.1:8080` is a separate local
preview and is available only while its local server runs. The earlier local Codex schedule
is superseded once the cloud deployment is verified. `refresh_schedule.json` keeps the
page's countdown in sync; change both that file and the workflow when changing the schedule.

An open page checks the local refresh marker every minute and when you return to the tab,
then reloads automatically after a successful rebuild. Refresh markers are published after
the page is rebuilt, and incomplete downloads preserve the previous cached results.

## History, teams, and refresh health

`data/forecast_history.json` retains each successful published forecast. Rebuilding the same
forecast timestamp does not add duplicates. The history starts with an archived July 30
project output and the October 27 cloud forecast; gaps are shown honestly rather than
backfilled. Charts, percentage-point changes, and per-team CSV downloads use these snapshots.

All teams in the current season have pages at `/teams/<team-name>/`, with regular-season
records and scoring averages, separate playoff records, recent results, regular-season
head-to-head records, and forecast history. Teams outside the modeled eight-team bracket
show that distinction instead of inventing probabilities.

`public/refresh_health.json` reports the latest attempt, last success, data date, and game
coverage. The app checks it every minute and flags refreshes more than two hours overdue.
If the main cloud job fails, a separate job checks out the last published forecast and
publishes only a failure notice; saved predictions and history stay intact. If deployment
itself is unavailable, the overdue indicator can still warn about the old published data.

Completed playoff games are retained in both the forecast and interactive bracket. Only
unplayed games are simulated, so eliminated teams cannot return. Once the playoffs start,
actual first-round pairings resolve tied seeds. The page shows the latest completed game
date and labels market odds that still price eliminated teams as stale.

## Rosters and missing players

The daily pipeline refreshes ESPN season rosters and injury reports, and caches parsed
2025–26 player box scores in `data/player_game_stats.csv`. Current reports, coverage, and
per-player forecast treatment are stored in `data/player_availability.json` and displayed
on each team page. A fresh feed timestamp does not make an old individual report current.

The availability layer is **experimental**. It estimates shrunken associations between
player participation and score residuals, with no claim of causal injury effects or
independent injury-adjusted calibration. A point-margin-to-log-odds mapping is fitted on
historical score-form features. The existing validation and SHAP charts describe only
the score-only baseline; both baseline and adjusted title estimates are displayed.

**Score-only is the default.** Published odds, team pages, daily cloud refreshes, and
new history entries use score-only predictions. Verified player data makes an optional
injury-adjusted comparison available, but does not enable it automatically. The
interactive bracket's injury toggle starts unchecked on every page load; switching
models restores the published score-only leaderboard, and a new interactive Monte
Carlo can then compare the selected model. Earlier injury-adjusted history is retained
with its original label. There is no automatic promotion after a favorable backtest;
the adjustment stays optional pending clear evidence of improvement and an explicit
decision to change the default.

Only confirmed absences are applied. Season-long reports persist through the bracket;
fresh game-specific reports are limited to the next scheduled game within 72 hours.
Questionable/probable statuses, old reports contradicted by later appearances, and ambiguous
roster assignments do not create assumed absences. Penalties are discounted by prior
participation to avoid double counting missed time already in team form. Player effects
are capped at four margin points and team effects at six. No effect is invented when
there is no usable participation comparison.

The model requires at least 98% archive coverage and complete current-season player
history for each adjusted team. The initial archive has 635 of 637 games; the two ESPN
404s affect New York, Dallas, Chicago, and Minnesota, which retain their baseline strength.
Current finalists have complete player history. Unverified or stale feeds disable the
adjustment and mark player data as partial. Cached roster information is labeled separately.
Minute restrictions and mid-game injuries are not forecast. Interactive bracket controls
can switch between adjusted and score-only game probabilities without rewriting history.

## Historical test of the injury adjustment

Run `python scripts/collect_historical_injuries.py` using a Python runtime with
`pdfplumber` (the bundled PDF runtime is supported), then run
`.venv/Scripts/python.exe -X utf8 scripts/backtest_availability.py`.
The comparison uses dated official pregame reports and monthly player models
trained only on earlier games. It does not reuse today's injury snapshot.
`scripts/audit_historical_injuries.py` independently checks PDF status-cell counts
and team/matchup assignments. The report collector and audit require `pdfplumber`;
the numerical test uses the existing project dependencies.

Results, game-level predictions, uncertainty intervals, and a chart are saved in
`outputs/availability_backtest/`. The initial 2026 test covered 202 games with
explicit reports for both teams: winner accuracy was 72.28% for both models;
log-loss and Brier score improved only slightly, with uncertainty intervals
including no improvement. Only five covered games were playoff games.
These findings do not validate championship probabilities or the complete ESPN
injury/roster-fetch pipeline. Retain the experimental label; see
`outputs/availability_backtest/REPORT.md` for methodology and coverage limitations.
Running the standalone backtest does not rebuild or publish live forecasts.

The app's **Backtest** section at `/#backtest` displays this evaluation,
with paired accuracy/log-loss/Brier comparisons, uncertainty intervals, sample
selection, coverage warnings, and downloads. The existing daily cloud refresh
also runs `src/evaluation.py`: it reuses the hashed report manifest, fetches reports
for newly completed games, and appends only previously unseen prediction rows.
Earlier rows are never re-predicted. The initial study is frozen in
`data/backtests/initial_results.json` and `initial_predictions.csv`.

A separate prospective trial records the first paired production game prediction
5 minutes to 24 hours before scheduled tip, using a verified player snapshot fetched
within two hours. The probabilities, model hash, timestamp, and team-level injury/roster
evidence are saved immediately in `data/backtests/prospective_predictions.json`.
Matching completed results are scored on subsequent daily checks. Missing pregame
captures are never reconstructed after the fact. Daily 7 a.m. Pacific sampling can
miss early games and last-minute updates. The trial uses production regular-season
form; historical walk-forward results use running pregame form, so the cohorts stay
separate. This project currently evaluates the 2026 season.

The app shows the last check, failures, pending/scored prospective counts, the frozen
study, newly evaluated games, and cumulative accuracy-difference checkpoints.
Unchanged daily checks add no points. Empty cohorts show no inferred accuracy.
`outputs/availability_backtest/auto_status.json`, `progress.json`, and `prospective.csv`
are exported alongside the main evaluation and pregame journal. Repeated checkpoints
are not independent significance tests. Score-only remains default; automatic
monitoring never promotes injury adjustments.

Evaluation updates stage their output and roll back a failed promotion. A failed
evaluation preserves the last successful metrics and publishes a failure notice,
while score-only forecast refreshes can continue. Pregame journal captures survive
a later retrospective evaluation failure. Use `python src/evaluation.py --offline`
to check cached data without retrieving new historical reports.

## How it works (build order)

| Stage | Script | What it does |
|---|---|---|
| 1. Fetch | `src/fetch_espn.py` | Game logs 2016–2026 from ESPN's public JSON API → `data/all_games.csv` |
| 2. Features | `src/features.py` | Leakage-free per-team form features → matchup table with feature *differences* |
| 3. Model | `src/model.py` | Logistic + gradient-boosting, **time-based** validation (log-loss / Brier / calibration) |
| 4. Simulate | `src/simulate.py` | Monte-Carlo the real bracket 20,000×, game by game → Finals & title probabilities |
| 5. Visuals | `src/visuals.py` | Finals-probability bar chart |
| 6. Explain | `src/explain.py` | SHAP global summary + local matchup explanations |
| 7. Compare | `src/compare_odds.py` | Model vs. live ESPN BET championship futures (de-vigged) |

Each script also runs standalone (e.g. `python src/simulate.py`) once the earlier stages
have produced their cached files.

## Outputs

- `SUMMARY.md` — written prediction + interpretation
- `outputs/finals_probabilities.png` / `.csv` — each team's Finals & title probability
- `outputs/calibration.png` — reliability of the model's probabilities on held-out seasons
- `outputs/shap_summary.png`, `outputs/shap_local_*.png` — feature importance & per-matchup explanations
- `outputs/model_vs_market.png` — model vs. sportsbook sanity check
- `outputs/validation_metrics.csv` — held-out metrics table

## Design choices worth knowing

- **Data source:** ESPN's public API is used for *all* seasons (not Kaggle) so history and
  the live season share one schema; Basketball-Reference blocks automated requests.
- **No leakage:** every form feature uses only games played *before* the game it describes
  (expanding/rolling stats with a one-game shift), and validation splits by time, never
  randomly.
- **Antisymmetric model:** every game is trained in both team orientations, so
  P(A beats B) + P(B beats A) = 1 by construction — important for a fair bracket sim.
- **Series are simulated game-by-game**, with home court assigned to the higher seed per
  the league's real host patterns — not as a single per-series coin flip.

See `SUMMARY.md` → *Honest limitations* for what the model can and cannot see.

## Live context and cloud alerts

The **Live context** section polls the fixed WNBA ESPN endpoints through a Vercel
Node function every 60 seconds while the page is visible. The function caches
responses briefly, bounds source timeouts, rejects arbitrary URLs, and returns an
explicit unavailable state on failure. Report dates remain visible. A recent-usage
rotation (five highest minute averages across three covered games) is a projection,
not a confirmed starting lineup. Source-listed starters and actual minutes are
displayed separately when supplied for a selected game.

The optional player model now accepts a fresh, explicitly stated numeric minute
restriction, scaled by the player's usual minutes. Negated, speculative, stale,
contradicted, or nonnumeric restrictions receive no invented penalty. This changes
the model version to `participation-ridge-minutes-v2`; the old historical study does
not validate this extension. The mid-game scenario estimates lost remaining
regulation point-margin contribution only. It does not infer injuries from playing
time, update the published pregame forecast, or claim calibrated live win odds.

`.github/workflows/cloud-monitor.yml` runs hourly at minute 17 UTC, independently
of a local computer. It creates GitHub issues assigned to `chepkemboiedel-sudo`
for material fresh availability changes affecting a game within 24 hours, a
qualifying prospective improvement, or three consecutive failed source checks.
The first successful check establishes the injury baseline without mass alerts.
Repeated reports stay quiet. Issue markers and saved state prevent duplicates
across reruns. Delivery by email/push depends on the account's GitHub notification
settings. GitHub scheduling and ESPN reporting can be delayed; this is not an
instant-alert guarantee. Full forecast generation remains daily at 7 a.m. Pacific.

The workflows require repository-scoped `contents:write` and `issues:write` through
the built-in Actions token; no new personal access token or paid feed is needed.
`/live_health.json` reports the actual hourly check status. `/operations.json`
exports evidence policy, missing box scores and report coverage, season readiness,
and registered championship predictions. Failed historical reports are retried
weekly; verified reports and prior scored predictions remain frozen.

## Automatic selection and future seasons

Score-only remains the current default. `src/promotion.py` can switch published
and interactive defaults only for the current model version and season after an
untouched prospective block passes every preregistered check: 100 games, 30
distinct game days spanning at least 30 days, 30 changed probabilities, winner
accuracy gain of at least 1 percentage point, positive paired accuracy interval,
negative paired log-loss and Brier intervals, and a qualifying exact McNemar test.
Blocks reserve slots by pregame capture time, including pending games, so delayed
results cannot reshuffle the test. Checks use day-clustered paired bootstrap
intervals with 20,000 deterministic resamples. Across fixed look k, the total
allowance is `0.05/(k*(k+1))`, divided across the three intervals and McNemar.
The intervals are approximate, conditional on the model, and are not proof of
future generalization. Historical study results and daily cumulative charts
cannot trigger selection. A new model version or season starts a new evidence
stream. An unavailable, stale, or wrong-season player snapshot forces score-only
even after a qualifying decision. The publisher independently rechecks the gate.

The fetcher follows the calendar year and preserves prior caches when a new
season has no completed games. The forecast rolls forward only when at least
eight teams each have three completed regular-season games. Training and held-out
validation windows roll forward without including the forecast season in final
score-model training. Team pages and history respect the displayed season.
Future playoff formats are labelled provisional until reviewed against league
rules; the last verified eight-team best-of-3/5/7 format is not a guarantee about
future rule changes.

Championship validation registers one first qualifying pre-playoff forecast per
season when a postseason game appears in the upcoming schedule. It settles after
the champion is established under a verified bracket format. Today's Finals
probabilities cannot be backfilled as independent preseason evidence. Complete
public injury coverage and improved championship accuracy cannot be promised;
unavailable observations stay explicit, and more prospective games are required.

## Validated source recovery — October 27, 2026

The missing May 29 Minnesota–Chicago player box score was recovered from ESPN's
Core API and corroborated against the official WNBA box score. All 27 athlete
identities and participation statuses were matched uniquely. Player points,
rebounds and assists agree between sources, team scores are 79–58, and individual
WNBA minute clocks sum to 200:01 per team (one second of aggregate rounding).
The original clocks are retained. A validated archive supplies the fallback when
the usual ESPN summary endpoint remains unavailable, bringing coverage to 637/637.

Five fixed-time official injury PDFs from July 3–5 were recovered by accepting
their identifiable WNBA sections and excluding four explicitly unsubmitted NBA
placeholder rows in each file. Publication timestamps and PDF hashes are recorded;
unknown teams, NBA player records, and mismatched WNBA matchups still fail
validation. Parser version 3 retains compatibility with already verified clean
version 2 reports. The July 28 and August 23 15:00 ET files still return HTTP 403,
including alternate public CDN checks, and the public archive search found no
copies. No differently timed report was substituted. Current archive coverage is
151/153 reports.

The new coverage panel and `/data_recovery.json` distinguish current source
coverage from the historical study's original coverage. Recovery does not rescore
old games: original backtest JSON, predictions CSV, comparison chart, and frozen
initial-study files were checked against their pre-recovery SHA-256 hashes.
Daily evaluation continues to append only genuinely new games. Raw recovered PDFs,
parsed WNBA-only reports, the corroborated box-score archive, and the recovery
receipt are retained under `data/recovery/` and `data/backtests/injury_reports/`.

