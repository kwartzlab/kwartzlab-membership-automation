from services.kos_api import is_active_or_hiatus
from workspace_membership_audit import (
    _normalize_email_for_match,
    _resolve_workspace_match,
    _split_missing_group_results,
    load_workspace_audit_config,
)


def test_load_workspace_audit_config_parses_groups(monkeypatch):
    monkeypatch.setenv("KOS_API_BASE_URL", "http://example.test")
    monkeypatch.setenv("KOS_API_TOKEN", "token")
    monkeypatch.setenv("GOOGLE_WORKSPACE_DOMAIN", "kwartzlab")
    monkeypatch.setenv("GOOGLE_WORKSPACE_GROUPS", "members@kwartzlab.ca,announce@kwartzlab.ca")
    cfg = load_workspace_audit_config()
    assert cfg.google_workspace_groups == ["members@kwartzlab.ca", "announce@kwartzlab.ca"]


def test_is_active_or_hiatus():
    assert is_active_or_hiatus({"status": "active"}) is True
    assert is_active_or_hiatus({"status": "ACTIVE"}) is True
    assert is_active_or_hiatus({"status": "inactive"}) is False
    assert is_active_or_hiatus({"status": None}) is False


def test_split_missing_group_results():
    rows = [
        {"workspace_email": "a@kwartzlab.ca", "missing_groups": ["g1", "g2"]},
        {"workspace_email": "b@kwartzlab.ca", "missing_groups": ["g1"]},
        {"workspace_email": "c@kwartzlab.ca", "missing_groups": []},
    ]
    full, partial = _split_missing_group_results(rows, ["g1", "g2"])
    assert [row["workspace_email"] for row in full] == ["a@kwartzlab.ca"]
    assert [row["workspace_email"] for row in partial] == ["b@kwartzlab.ca"]


def test_normalize_email_for_match_removes_special_chars():
    assert _normalize_email_for_match("First.Last-Name@kwartzlab.ca", "kwartzlab") == "firstlastname@kwartzlab.ca"
    assert _normalize_email_for_match("first_lastname@kwartzlab.ca", "kwartzlab.ca") == "firstlastname@kwartzlab.ca"
    assert _normalize_email_for_match("first.lastname@example.com", "kwartzlab") == ""


def test_resolve_workspace_match_uses_recovery_email_when_name_missing():
    user = {"id": 1, "email": "person@example.com", "status": "inactive"}
    result = _resolve_workspace_match(
        user,
        workspace_domain="kwartzlab.ca",
        workspace_users=set(),
        normalized_workspace_index={},
        recovery_index={"person@example.com": {"person@kwartzlab.ca"}},
    )
    assert result["workspace_exists"] is True
    assert result["workspace_email"] == "person@kwartzlab.ca"
    assert result["email_match_source"] == "google_recovery_email"


def test_resolve_workspace_match_handles_missing_name_and_no_recovery():
    user = {"id": 2, "email": "unknown@example.com", "status": "inactive"}
    result = _resolve_workspace_match(
        user,
        workspace_domain="kwartzlab.ca",
        workspace_users=set(),
        normalized_workspace_index={},
        recovery_index={},
    )
    assert result["workspace_exists"] is False
    assert result["error"] == "missing_name_fields"
