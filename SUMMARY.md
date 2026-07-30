# 2026 WNBA Finals — Prediction Summary

*Generated from data through 2026-07-30 (season in progress). Re-run `python run_all.py` to refresh.*

---

## Headline

The model simulates the **actual** 2026 playoff format — top-8 seeding regardless of
conference, then a 3-round bracket (best-of-3 → best-of-5 → best-of-7), with each
individual game drawn from a validated per-game win-probability model — **20,000 times**.

**Most likely Finals:** the two clearest favorites to *reach* the Finals are the
**Minnesota Lynx** (46.8%) and, out of the other bracket half, the
**Golden State Valkyries** (36.6%) or **Las Vegas Aces** (36.3%). The single most
likely Finals pairing is **Minnesota vs. Las Vegas (17.2%)**, essentially tied with
**Minnesota vs. Golden State (17.1%)**.

**Most likely champion:** **Minnesota Lynx, 29%** — a clear favorite but far from a
lock, consistent with the historical pattern that even a dominant #1 seed wins only
~60–80% of the time it reaches the Finals.

---

## Full results — all 8 playoff-bracket teams

| Seed | Team | Conf | Reg. Win% | **Reach Finals** | **Champion** |
|---:|---|---|---:|---:|---:|
| 1 | Minnesota Lynx | West | .793 | **46.8%** | **29.0%** |
| 3 | Golden State Valkyries | West | .679 | 36.6% | 18.5% |
| 2 | Las Vegas Aces | West | .704 | 36.3% | 16.8% |
| 4 | Indiana Fever | East | .643 | 33.7% | 19.6% |
| 6 | Atlanta Dream | East | .630 | 17.3% | 6.1% |
| 5 | Dallas Wings | West | .643 | 16.4% | 7.2% |
| 7 | New York Liberty | East | .571 | 9.8% | 2.4% |
| 8 | Washington Mystics | East | .556 | 3.2% | 0.5% |

**Why Indiana's title odds (19.6%) beat its reach-Finals odds ranking:** Indiana (#4)
shares the top bracket half with Minnesota, so it usually has to *beat the strongest
team in the field* to reach the Finals. When it does break through, it arrives
battle-tested and faces a weaker bottom-half opponent — so it converts a high share of
its Finals appearances into titles. This is a structural bracket effect the simulation
captures that a naïve "better seed = better odds" ranking would miss.

*(Each bracket half produces exactly one finalist, so the four top-half teams'
reach-Finals probabilities sum to 100%, as do the four bottom-half teams'.)*

---

## Secondary cut — conference representation

Conference plays **no role** in the format; this is illustrative only. Because the West
holds the #1 seed plus two of the three next-strongest teams, an all-West Finals is the
single most likely outcome:

| Finals matchup | Probability |
|---|---:|
| Both West | **46.3%** |
| Mixed (one West, one East) | 43.4% |
| Both East | 10.3% |

The likeliest East representative in the Finals is the **Indiana Fever** (33.7% to reach).

---

## How the model was built & validated

1. **Data** — Game-by-game logs for **2016–2026** (2,516 games incl. playoffs) pulled
   from ESPN's public JSON API. One consistent schema for every season; no scraping, no
   login. The computed 2026 standings match the official snapshot exactly.
2. **Features** (per team, strictly from *earlier* games — no leakage): win%, season &
   last-10 point differential, Pythagorean win expectation (exponent 13.91), home/away
   split, strength of schedule, and rest days. The model sees the **difference** between
   the two teams' features plus a home-court flag.
3. **Models** — Logistic regression (interpretable baseline) and gradient boosting,
   compared head-to-head.
4. **Validation** — **Time-based** split (train 2016–2023, test 2024–2025). Both models
   beat the "better regular-season record wins" baseline on the metrics that matter for
   simulation:

   | Model | Log-loss ↓ | Brier ↓ | Accuracy |
   |---|---:|---:|---:|
   | Baseline (better record) | 0.644 | 0.225 | 0.670 |
   | Logistic regression | 0.611 | 0.212 | 0.655 |
   | Gradient boosting | **0.608** | **0.210** | **0.679** |

   Both models are well-calibrated (see `outputs/calibration.png`). The **logistic model
   is used as the simulation engine** — it is naturally antisymmetric
   (P(A beats B) + P(B beats A) = 1) and its probabilities track observed win rates closely.

---

## What drives the predictions (SHAP)

From `outputs/shap_summary.png`, in order of impact:

1. **Pythagorean edge** — by far the biggest driver. A team's points-for/against ratio
   predicts future wins better than its raw W-L record.
2. **Home court** — a real, consistent bump.
3. **Recent form (last-10 point differential)** and **strength of schedule**.

> **Modeling note for learning:** the logistic model gives raw *win%* a small *negative*
> coefficient. That's **collinearity**, not a claim that winning hurts — win%, point
> differential, and Pythagorean expectation all measure "how good is this team," and once
> the two margin-based features carry that signal, the leftover independent contribution
> of raw win% flips sign. It doesn't hurt predictions (the model is well-calibrated), but
> it's a good example of why linear-model coefficients must be read as a group.

Local explanations for marquee matchups are in `outputs/shap_local_*.png` (e.g. Minnesota
hosting Las Vegas → model gives Minnesota ~60%).

---

## Sanity check vs. the betting market (ESPN BET, de-vigged)

| Team | Model | Market | Diff |
|---|---:|---:|---:|
| Minnesota Lynx | 29.0% | 22.2% | +6.8% |
| Indiana Fever | 19.6% | 19.9% | **−0.3%** |
| Las Vegas Aces | 16.8% | 19.9% | −3.1% |
| Golden State Valkyries | 18.5% | 3.0% | **+15.5%** |
| New York Liberty | 2.4% | 11.1% | −8.7% |

- **Strong agreement** on Minnesota (both favor), and near-**exact** agreement on Indiana
  and Las Vegas — a good sign the model is sane.
- **Biggest disagreement: Golden State.** The score-only model rates the Valkyries a
  top-3 title threat on the strength of their point differential; the market treats them
  as a longshot. The market is almost certainly pricing in information the model *cannot
  see* — roster construction, playoff experience (a young 2025 expansion franchise), and
  injuries. **Treat GSV's model number with caution.**
- The market also rates **New York** far higher than the model (brand/roster pedigree the
  record doesn't reflect), and carries stale-looking futures on Phoenix/Seattle despite
  their poor current records.

---

## Honest limitations

- **The model knows only scores.** It has no roster, injury, minutes, or trade
  information. Golden State and New York are where that blind spot shows most.
- **Rest is neutralized in the playoffs** (`d_rest = 0`) — the sim doesn't model a team
  resting after a sweep, or fatigue from a Game-3 grind.
- **Seeding tiebreakers are simplified** (win% then point differential) rather than the
  league's full head-to-head chain; the Indiana/Dallas #4-#5 order depends on this.
- **The season is still in progress.** These numbers move as results come in — re-run the
  pipeline to update. Championship futures were also captured live and may lag current form.
- The 2020 "bubble" season and the FIBA/Olympic mid-season breaks make rest and
  schedule-strength features noisier in some historical years.
