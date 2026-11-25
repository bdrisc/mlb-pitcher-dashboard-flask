from app.services.pitcher_profiles import _rounded


def test_profile_rounding_is_stable_at_decimal_boundaries():
    for value, digits, expected in (
        (86.84999999999998, 1, 86.9),
        (86.85000000000001, 1, 86.9),
        (5.749999999999996, 1, 5.8),
        (6.749999999999995, 1, 6.8),
        (0.35349999999999994, 3, 0.354),
        (0.35350000000000004, 3, 0.354),
        (-6.755000000000001, 2, -6.76),
        (-6.754999999999999, 2, -6.76),
        (86.84999, 1, 86.8),
    ):
        assert _rounded(value, digits) == expected
    assert _rounded(None) is None


def test_profile_rounding_rejects_nonfinite_values():
    for value in (float("inf"), float("-inf"), float("nan")):
        assert _rounded(value) is None
