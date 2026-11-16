"""The published xRV validation is reproducible and fails safely with no data."""

import pytest

from scripts.audit_xrv import _corr, audit_season


def test_correlation_helper():
    assert _corr([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert _corr([1, 1, 1], [1, 2, 3]) is None
    assert _corr([], []) is None


def test_empty_database_audit_is_explicit(app):
    with app.app_context():
        result = audit_season(2026)
    assert result["pitchers"] == 0
    assert result["physical_pitches"] == 0
    assert result["contact_coverage_pct"] is None
    assert result["split_half"]["status"] == "insufficient sample"
