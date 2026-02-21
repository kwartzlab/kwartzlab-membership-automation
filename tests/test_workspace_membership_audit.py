from workspace_membership_audit import (
    _is_active_user,
    _normalize_email_for_match,
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
    assert cfg.kos_users_list_path == "/api/users"


def test_is_active_user():
    assert _is_active_user({"status": "active"}) is True
    assert _is_active_user({"status": "ACTIVE"}) is True
    assert _is_active_user({"status": "inactive"}) is False
    assert _is_active_user({"status": None}) is False


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
    assert (
        _normalize_email_for_match("First.Last-Name@kwartzlab.ca", "kwartzlab")
        == "firstlastname@kwartzlab.ca"
    )
    assert (
        _normalize_email_for_match("first_lastname@kwartzlab.ca", "kwartzlab.ca")
        == "firstlastname@kwartzlab.ca"
    )
    assert _normalize_email_for_match("first.lastname@example.com", "kwartzlab") == ""
