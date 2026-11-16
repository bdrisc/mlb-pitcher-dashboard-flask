"""Presentation thresholds for reproducible expected RV comparisons."""

import pytest

from app.services.expected_run_value import xrv_quality_status


@pytest.mark.parametrize(
    ("scored", "physical", "contact_total", "contact_scored", "expected"),
    [
        (0, 0, 0, 0, "unavailable"),
        (100, 100, 0, 0, "small_sample"),
        (200, 205, 50, 49, "small_sample"),
        (400, 400, 50, 50, "descriptive"),
        (400, 400, 50, 46, "limited_coverage"),
        (360, 400, 50, 50, "limited_coverage"),
        (400, 400, 29, 28, "small_sample"),
        (400, 400, 30, 29, "descriptive"),
    ],
)
def test_xrv_quality_guardrails(scored, physical, contact_total, contact_scored, expected):
    assert (
        xrv_quality_status(
            scored=scored,
            physical=physical,
            contact_total=contact_total,
            contact_scored=contact_scored,
        )
        == expected
    )
