"""Pitch-type transition probabilities from verified consecutive same-PA pitches.

The existing tunneling aggregation already enumerates adjacent, classified
pitch pairs without requiring trajectory tracking. Reusing its *observed*
counts avoids a second database query and keeps second-pitch filter semantics
identical to the separation table.
"""

from __future__ import annotations

from collections import Counter

from app.services.pitch_data import PITCH_NAME_MAP


def build_pitch_transition_matrix(tunneling: dict) -> dict:
    """Row-normalized P(next pitch type | previous pitch type) for observed pairs."""
    counts: Counter[tuple[str, str]] = Counter()
    outgoing: Counter[str] = Counter()
    incoming: Counter[str] = Counter()

    for pair in tunneling["pairs"]:
        first, second = pair["pitch_a"], pair["pitch_b"]
        count = int(pair["observed_pair_count"])
        if count <= 0:
            continue
        counts[(first, second)] += count
        outgoing[first] += count
        incoming[second] += count

    total = sum(outgoing.values())
    types = sorted(
        set(outgoing) | set(incoming),
        key=lambda code: (-(outgoing[code] + incoming[code]), code),
    )
    pitch_types = [
        {
            "pitch_type": code,
            "pitch_name": PITCH_NAME_MAP.get(code, code),
            "outgoing_transitions": outgoing[code],
            "incoming_transitions": incoming[code],
        }
        for code in types
    ]
    rows = []
    for first in types:
        denominator = outgoing[first]
        if denominator == 0:
            continue
        rows.append(
            {
                "pitch_type": first,
                "pitch_name": PITCH_NAME_MAP.get(first, first),
                "total": denominator,
                "cells": [
                    {
                        "pitch_type": second,
                        "count": counts[(first, second)],
                        "pct": round(100 * counts[(first, second)] / denominator, 1),
                    }
                    for second in types
                ],
            }
        )

    return {
        "method": "consecutive_same_pa_pitch_type_v1",
        "filter_pitch": "second",
        "denominator": "observed_transitions_from_previous_with_filtered_next_pitch",
        "includes_same_type_pairs": True,
        "total_transitions": total,
        "pitch_types": pitch_types,
        "rows": rows,
    }
