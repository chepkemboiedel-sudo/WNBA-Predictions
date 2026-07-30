# WNBA 2026 Finals Prediction
Link: https://wnba-predictions-4oai-eotji3xav-chepkemboiedel-sudos-projects.vercel.app/
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

That runs the whole pipeline and writes every chart + CSV to `outputs/`. The first run
downloads ~11 seasons from ESPN (a few minutes); afterwards historical seasons are cached
and only the live 2026 season is refreshed. Use `python run_all.py --refresh` to force a
full re-download, or `--sims 50000` for more simulations.

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
