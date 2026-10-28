# Historical injury-adjustment test

The test does not establish an improvement in prediction quality. Winner accuracy changed by +0.00 percentage points. Log-loss changed by -0.000813 and Brier score by -0.000113. Both probability-score uncertainty intervals include zero.

## Results

Primary comparison: 202 held-out 2026 games with an explicitly submitted report for both teams. Lower log-loss and Brier score are better; higher winner accuracy is better.

| Metric | Score-only | With absence adjustment | Change (adjusted minus baseline) | 95% interval for change |
|---|---:|---:|---:|---:|
| log loss | 0.556734 | 0.555921 | -0.000813 | -0.003812 to +0.002450 |
| brier | 0.186297 | 0.186184 | -0.000113 | -0.001442 to +0.001337 |
| accuracy | 72.28% | 72.28% | +0.00 pp | -1.48 to +1.46 pp |

The adjustment corrected 1 winner picks and harmed 1; two-sided exact McNemar p = 1.000. Intervals use 10,000 paired bootstrap resamples of game days, keeping games played on the same day together. They are approximate, conditional on the fitted models, and do not establish generalization to future seasons.

## Additional comparisons

| Sample | Games | Changed probabilities | Baseline accuracy | Adjusted accuracy | Log-loss change | Brier change |
|---|---:|---:|---:|---:|---:|---:|
| all eligible games | 324 | 120 | 69.14% | 69.14% | -0.000507 | -0.000070 |
| verified report games | 202 | 120 | 72.28% | 72.28% | -0.000813 | -0.000113 |
| verified reports with out | 197 | 120 | 72.59% | 72.59% | -0.000834 | -0.000116 |
| changed games | 120 | 120 | 70.83% | 70.83% | -0.001368 | -0.000190 |
| regular season | 197 | 117 | 72.59% | 72.59% | -0.000834 | -0.000116 |
| playoffs | 5 | 3 | 60.00% | 60.00% | -0.000000 | +0.000018 |

## Method and safeguards

- Score-only logistic regression is fitted on 2016-2025 games. Held-out games are in 2026; early games lacking the existing feature minimum are excluded. Each game contributes once, from the home team's perspective.
- Player effects are refitted at the start of each month using only preceding games, including 2025 box scores and earlier 2026 regular-season games. The existing ridge penalty, positive-effect clipping, participation discount, probability mapping, and player/team caps are retained without tuning to these results.
- Official report selection is fixed before scoring: 09:00 ET for games tipping before 16:00 ET, otherwise 15:00 ET, with at least one hour before tip. Eastern dates are derived from recorded scheduled game timestamps, not UTC game-log dates.
- Both teams must be explicitly submitted for the exact date and matchup. Missing, unsubmitted, malformed, or wrong-league reports produce the score-only fallback. An omitted team is not inferred to be healthy. This conservative rule makes the covered subset unrepresentative of the whole league.
- Only Out/Suspended records trigger an absence. Doubtful, Questionable, Probable, and Available do not. Each game uses its own report; no report is carried into subsequent games.
- Report names are normalized and matched uniquely to athlete IDs seen in earlier box scores. Current rosters, today's ESPN statuses, future aliases, future participation, and the test game's box-score statistics are not prediction inputs. The scheduled start timestamp is the only field taken from the held-out game's box-score record.
- Prior participation and team archive completeness use games strictly before the report's UTC calendar date, conservatively omitting earlier games on that date. Incomplete prior player history disables that team's penalty. Training folds exclude the entire test month and all later dates.

## Coverage and limits

- 146 of 153 fixed-time report files passed validation. Five URLs returned documents containing non-WNBA teams; two returned HTTP 403.
- Of 324 eligible 2026 games, 202 had both-team report coverage. The remaining games use the same baseline in both comparisons. Only 5 covered games are playoff games, which is too small to validate championship forecasts.
- 589 Out/Suspended player-game records were considered; 7 could not be matched to a unique previously seen athlete and received no invented effect. 56 covered games had an incomplete prior archive for at least one side; that side retained baseline strength.
- This tests the existing numerical adjustment with independently archived official statuses. It does not recreate historical ESPN fetches, roster snapshots, feed delays, return-date fields, or the full season-long-report propagation logic. Those were not archived. It therefore does not certify the complete live injury pipeline.
- Historical game probabilities use the model's pregame running-form features, which include earlier playoff games. Production bracket simulations use a fixed regular-season form snapshot and neutral rest. These are not a direct backtest of series or championship probabilities.
- Test outcomes influenced neither report-time selection nor hyperparameter selection. The model was not retuned or promoted after viewing these results. The report-covered subset is selected by data availability, so its accuracy must not be compared directly with the all-games accuracy as if model quality changed.

## Reproduce

1. Use the bundled PDF Python runtime (pdfplumber required) to run `python scripts/collect_historical_injuries.py`. It downloads archived PDFs into `tmp/pdfs/historical_injuries/` and writes dated, hashed records plus the manifest under `data/backtests/`.
2. Run `.venv/Scripts/python.exe -X utf8 scripts/backtest_availability.py`. It uses the manifest and existing game/player caches; no network access or live forecast rebuild is required.
3. Inspect `predictions.csv` for every game, selected report URL/timestamp, model cutoff, fallback reason, probability pair, and per-player treatment. `results.json` includes monthly fits, subgroups, and uncertainty intervals.

Sources: [Official WNBA injury reporting rules](https://www.wnba.com/wnba-injury-report). Every downloaded report's exact source URL and SHA-256 are recorded in `data/backtests/injury_report_manifest.json`.

Recommendation: retain the experimental label. These results do not justify claiming better accuracy. Collect prospective ESPN report/roster snapshots and evaluate a larger untouched sample before promoting or retuning the live adjustment.

## Automatic monitoring

Checked 2026-10-28T01:32:45.994109Z. Historical predictions are append-only. The initial study is frozen separately; 0 later completed games have been evaluated. New archived-report rows are retrospective walk-forward evaluations, not prospective forecasts.

The separate prospective trial freezes the first paired production game prediction within 24 hours before scheduled tip, using a player snapshot fetched within two hours. Captured probabilities, model hash, and relevant roster/injury evidence are stored before outcomes. Missing pregame captures are never backfilled. There are 0 scored and 0 pending predictions. Daily 7 a.m. Pacific sampling may miss early games or last-minute injury updates. This trial uses fixed regular-season form, while the historical test uses pregame running form. Their results must not be pooled as one experiment.

Checkpoints are added only when scored evidence changes. Repeated daily checks do not count as new games or independent significance tests. The initial one-point trend is a starting checkpoint, not a historical performance curve. Score-only remains default; automatic promotion is evaluated separately using fixed prospective blocks; historical comparisons cannot promote a model.
