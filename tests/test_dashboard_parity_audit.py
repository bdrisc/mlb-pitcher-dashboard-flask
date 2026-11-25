from scripts.check_dashboard_parity import audit_exit_code


def test_empty_parity_audit_fails():
    assert audit_exit_code({"results": []}) == 1


def test_parity_audit_requires_successful_profiles():
    assert audit_exit_code({"results": [{"different_fields": 0}]}) == 0
    assert audit_exit_code({"results": [{"different_fields": 1}]}) == 1
    assert audit_exit_code({"results": [{"error": "failed"}]}) == 1
    assert audit_exit_code({"results": [{"different_fields": 0}], "game_differences": [1]}) == 1
