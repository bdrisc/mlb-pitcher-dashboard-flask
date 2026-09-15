"""Server-rendered visualizations used by Flask response routes."""

from __future__ import annotations

import io
import math

import matplotlib

matplotlib.use("Agg")

import pandas as pd
from matplotlib.figure import Figure

PITCH_COLORS = {
    "Four-Seam Fastball": "#D62828",
    "Two-Seam Fastball": "#F05D5E",
    "Fastball": "#D62828",
    "Sinker": "#F28E2B",
    "Changeup": "#2A9D68",
    "Slider": "#E0A800",
    "Sweeper": "#B88A00",
    "Curveball": "#67A9CF",
    "Knuckle Curve": "#4C78A8",
    "Cutter": "#8B1E3F",
    "Split-Finger": "#168A8A",
}


def render_movement_plot(frame: pd.DataFrame, pitcher_name: str) -> io.BytesIO:
    """Render an accessible movement chart and return PNG bytes."""
    figure = Figure(figsize=(7.5, 7.0), constrained_layout=True)
    axis = figure.subplots()

    for pitch_type, group in frame.groupby("pitch_type", dropna=False):
        label = str(pitch_type) if pd.notna(pitch_type) else "Unknown"
        axis.scatter(
            group["horizontal_break"],
            group["vertical_break"],
            label=label,
            color=PITCH_COLORS.get(label, "#59636E"),
            s=54,
            alpha=0.72,
            edgecolors="white",
            linewidths=0.5,
        )

    maximum = max(
        frame["horizontal_break"].abs().max(),
        frame["vertical_break"].abs().max(),
    )
    limit = max(20, math.ceil((float(maximum) + 2) / 5) * 5)
    axis.set_xlim(-limit, limit)
    axis.set_ylim(-limit, limit)
    axis.set_aspect("equal", adjustable="box")
    axis.axhline(0, color="#7B8490", linewidth=1)
    axis.axvline(0, color="#7B8490", linewidth=1)
    axis.grid(color="#DFE3E8", linewidth=0.8, linestyle="--", alpha=0.8)
    axis.set_axisbelow(True)
    axis.set_xlabel("Horizontal break (inches)")
    axis.set_ylabel("Induced vertical break (inches)")
    axis.set_title(f"{pitcher_name} Pitch Movement", fontsize=15, fontweight="bold")
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3, frameon=False)
    axis.spines[["top", "right"]].set_visible(False)

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=160, bbox_inches="tight")
    buffer.seek(0)
    return buffer
