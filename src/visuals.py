"""
visuals.py
==========
Headline chart: each playoff team's simulated probability of REACHING the Finals
(with its championship probability overlaid). Reads outputs/finals_probabilities.csv
produced by simulate.py.
"""

from __future__ import annotations

import os

import matplotlib.pyplot as plt
import pandas as pd

HERE = os.path.dirname(__file__)
OUT = os.path.abspath(os.path.join(HERE, "..", "outputs"))

CONF_COLOR = {"West": "#1f77b4", "East": "#d62728"}


def finals_bar(csv_path: str, out_path: str):
    df = pd.read_csv(csv_path).sort_values("p_reach_finals", ascending=True)
    labels = [f"({s}) {t}" for s, t in zip(df.seed, df.team)]
    colors = [CONF_COLOR.get(c, "#888") for c in df.conference]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.barh(labels, df.p_reach_finals * 100, color=colors, alpha=0.85, label="Reach Finals")
    # Championship probability as a darker inner bar.
    ax.barh(labels, df.p_champion * 100, color=colors, alpha=1.0, height=0.45)

    for y, (rf, ch) in enumerate(zip(df.p_reach_finals, df.p_champion)):
        ax.text(rf * 100 + 0.6, y, f"{rf:.0%}", va="center", fontsize=9)
        if ch >= 0.03:
            ax.text(ch * 100 - 0.6, y, f"{ch:.0%}", va="center", ha="right",
                    fontsize=8, color="white", fontweight="bold")

    ax.set_xlabel("Probability (%)")
    ax.set_title("WNBA — simulated Finals & championship probability\n"
                 "(outer bar = reach Finals, inner = win title; "
                 "blue = West, red = East)")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"Finals bar chart -> {out_path}")


if __name__ == "__main__":
    finals_bar(os.path.join(OUT, "finals_probabilities.csv"),
               os.path.join(OUT, "finals_probabilities.png"))

