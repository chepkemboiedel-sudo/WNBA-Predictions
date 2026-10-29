# 2026 WNBA forecast — refreshed results

Data through **Oct 29, 2026**, retrieved from ESPN. 2,659 games across 2016–2026,
including 22 completed 2026 playoff games.

**Finals: Golden State Valkyries and Atlanta Dream tied 3–3.**

The model gives **Golden State Valkyries a 54.5% championship probability**.
These estimates retain completed playoff results and simulate only the games still to play,
using 20,000 brackets. Eliminated teams cannot advance.

| Seed | Team | Reach Finals | Champion |
|---:|---|---:|---:|
| 2 | Golden State Valkyries | 100.0% | 54.5% |
| 4 | Atlanta Dream | 100.0% | 45.5% |
| 1 | Minnesota Lynx | 0.0% | 0.0% |
| 3 | Las Vegas Aces | 0.0% | 0.0% |
| 5 | Washington Mystics | 0.0% | 0.0% |
| 6 | Indiana Fever | 0.0% | 0.0% |
| 7 | Dallas Wings | 0.0% | 0.0% |
| 8 | New York Liberty | 0.0% | 0.0% |

The actual first-round pairings resolve tied regular-season seeds once playoffs begin.
Game probabilities come from logistic regression fitted to 2016–2025 score-based team form;
validation trains through 2023 and tests on 2024–2025. Validation metrics are in
`outputs/validation_metrics.csv`. These metrics validate the score-only baseline.
Published model: score-only. Automatic selection uses fixed prospective blocks, never the retrospective study.
The optional, experimental player-availability layer uses current ESPN rosters and verified absence
reports, with shrunken participation effects from 2025–2026 box scores. It has not been
independently calibrated and has not shown a clear improvement in the historical test.
The interactive toggle starts at the published model choice. Score-only title estimate for Golden State Valkyries:
54.5%.
Player-data status: Player feeds retrieved successfully.
Regular-season team-strength features stay fixed during the playoff simulation and playoff
rest differences are neutralized.

Market source status: ESPN returned a futures snapshot that still assigns odds to eliminated teams. These market odds appear stale and are shown for historical reference only. The model uses the latest completed playoff games.

Run `python run_all.py` to refresh data, forecasts, charts, and the website together.
