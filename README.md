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
Running the backtest does not rebuild or publish live forecasts.

The app's **Backtest** section at `/#backtest` displays this saved evaluation,
with paired accuracy/log-loss/Brier comparisons, uncertainty intervals, sample
selection, coverage warnings, and downloads. The evaluation date is separate from
the daily forecast refresh date. Daily site builds re-export the saved results;
they do not rerun the historical study or enable injury adjustments.

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
