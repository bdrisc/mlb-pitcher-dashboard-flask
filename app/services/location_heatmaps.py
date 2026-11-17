"""Full-filtered-sample plate-location KDEs by pitch type and batter hand.

Each panel uses the same catcher-view window and strike-zone overlay. A
regularized, Scott-scaled Gaussian kernel stays stable for clustered pitches,
and deterministic subsampling bounds very large individual pitch/hand groups.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from typing import Any

import numpy as np

KDE_MIN_PITCHES = 3
KDE_MAX_PITCHES = 2_500
X_GRID = np.linspace(-1.4, 1.4, 41)
Y_GRID = np.linspace(0.6, 4.4, 55)
STRIKE_ZONE = {"left": -0.88, "right": 0.88, "bottom": 1.2, "top": 3.8}


def _density_grid(coordinates: list[tuple[float, float]]) -> tuple[list[list[float | None]], int]:
    points = np.asarray(coordinates, dtype=float)
    if len(points) > KDE_MAX_PITCHES:
        indices = np.linspace(0, len(points) - 1, KDE_MAX_PITCHES, dtype=int)
        points = points[indices]

    sample_size = len(points)
    factor = sample_size ** (-1 / 6)  # Scott bandwidth for two dimensions
    covariance = np.cov(points, rowvar=False) * factor**2 + np.diag([0.09**2, 0.12**2])
    inverse_covariance = np.linalg.inv(covariance)
    xx, yy = np.meshgrid(X_GRID, Y_GRID)
    targets = np.column_stack((xx.ravel(), yy.ravel()))
    density = np.zeros(len(targets), dtype=float)

    for start in range(0, sample_size, 192):
        deviations = targets[:, None, :] - points[None, start : start + 192, :]
        squared_distance = np.einsum(
            "pni,ij,pnj->pn", deviations, inverse_covariance, deviations
        )
        density += np.exp(-0.5 * squared_distance).sum(axis=1)

    maximum = float(density.max())
    matrix = density.reshape(len(Y_GRID), len(X_GRID))
    if maximum > 0:
        matrix = matrix / maximum
    return [
        [round(float(value), 3) if value >= 0.05 else None for value in row]
        for row in matrix
    ], sample_size


def build_location_heatmaps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute smooth relative densities from all eligible filtered pitches."""
    by_group: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    usage: Counter[str] = Counter()
    names: dict[str, str] = {}

    for row in rows:
        if row["batter_side"] not in ("R", "L"):
            continue
        if row.get("description") in ("automatic_ball", "automatic_strike"):
            continue
        if row["plate_x"] is None or row["plate_z"] is None:
            continue
        x, y = float(row["plate_x"]), float(row["plate_z"])
        if not (isfinite(x) and isfinite(y)):
            continue
        code = row["pitch_type"]
        names.setdefault(code, row["pitch_name"])
        usage[code] += 1
        by_group[(code, row["batter_side"])].append((x, y))

    codes = sorted(usage, key=lambda code: (-usage[code], code))
    panels = []
    for code in codes:
        for side in ("R", "L"):
            coordinates = by_group.get((code, side), [])
            count = len(coordinates)
            density, sampled = _density_grid(coordinates) if count >= KDE_MIN_PITCHES else (None, 0)
            panels.append(
                {
                    "pitch_type": code,
                    "batter_side": side,
                    "pitch_count": count,
                    "kde_sample_count": sampled,
                    "density": density,
                }
            )

    return {
        "pitch_types": [
            {"pitch_type": code, "pitch_name": names[code], "pitch_count": usage[code]}
            for code in codes
        ],
        "panels": panels,
        "grid": {
            "x": [round(float(value), 3) for value in X_GRID],
            "y": [round(float(value), 3) for value in Y_GRID],
        },
        "strike_zone": STRIKE_ZONE,
        "min_kde_pitches": KDE_MIN_PITCHES,
    }
