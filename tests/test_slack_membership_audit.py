from services.kos_api import is_active_or_hiatus
from slack_membership_audit import (
    SlackAuditOverrides,
    _build_kos_email_index,
    _build_kos_id_index,
    _build_kos_name_index,
    _build_kos_name_related_indexes,
    _email_variants_for_matching,
    _is_human_slack_user,
    _map_slack_user_to_kos,
    _normalize_email,
    _normalize_name,
)


def test_normalize_name_removes_symbols_and_collapses_spaces():
    assert _normalize_name("  Jane-Doe (She/Her)  ") == "jane doe she her"


def test_is_human_slack_user_filters_bots_and_app_users():
    assert _is_human_slack_user({"id": "U1", "is_bot": False, "is_app_user": False}) is True
    assert _is_human_slack_user({"id": "USLACKBOT", "is_bot": False, "is_app_user": False}) is False
    assert _is_human_slack_user({"id": "U2", "is_bot": True, "is_app_user": False}) is False
    assert _is_human_slack_user({"id": "U3", "is_bot": False, "is_app_user": True}) is False


def test_map_slack_user_prefers_email_exact_match():
    kos_users = [
        {"id": 1, "email": "person@example.com", "first_name": "Person", "last_name": "One", "status": "active"},
        {"id": 2, "email": "other@example.com", "first_name": "Other", "last_name": "User", "status": "inactive"},
    ]
    slack_user = {
        "id": "U123",
        "profile": {
            "email": "person@example.com",
            "real_name": "Person One",
        },
    }

    matched, source, ambiguous = _map_slack_user_to_kos(
        slack_user,
        kos_id_index=_build_kos_id_index(kos_users),
        kos_email_index=_build_kos_email_index(kos_users),
        kos_name_index=_build_kos_name_index(kos_users),
        kos_last_name_index=_build_kos_name_related_indexes(kos_users)[1],
        kos_first_name_index=_build_kos_name_related_indexes(kos_users)[2],
        overrides=SlackAuditOverrides(set(), set(), {}, {}),
    )

    assert matched and matched["id"] == 1
    assert source == "email_exact"
    assert ambiguous == []


def test_map_slack_user_falls_back_to_name_exact_when_email_missing():
    kos_users = [
        {"id": 1, "email": "person@example.com", "first_name": "Person", "last_name": "One", "status": "active"},
    ]
    slack_user = {
        "id": "U123",
        "profile": {
            "real_name": "Person One",
        },
    }

    matched, source, ambiguous = _map_slack_user_to_kos(
        slack_user,
        kos_id_index=_build_kos_id_index(kos_users),
        kos_email_index=_build_kos_email_index(kos_users),
        kos_name_index=_build_kos_name_index(kos_users),
        kos_last_name_index=_build_kos_name_related_indexes(kos_users)[1],
        kos_first_name_index=_build_kos_name_related_indexes(kos_users)[2],
        overrides=SlackAuditOverrides(set(), set(), {}, {}),
    )

    assert matched and matched["id"] == 1
    assert source == "name_exact"
    assert ambiguous == []


def test_map_slack_user_reports_ambiguous_name():
    kos_users = [
        {"id": 1, "email": "person1@example.com", "first_name": "Person", "last_name": "One", "status": "active"},
        {"id": 2, "email": "person2@example.com", "first_name": "Person", "last_name": "One", "status": "inactive"},
    ]
    slack_user = {
        "id": "U123",
        "profile": {
            "real_name": "Person One",
        },
    }

    matched, source, ambiguous = _map_slack_user_to_kos(
        slack_user,
        kos_id_index=_build_kos_id_index(kos_users),
        kos_email_index=_build_kos_email_index(kos_users),
        kos_name_index=_build_kos_name_index(kos_users),
        kos_last_name_index=_build_kos_name_related_indexes(kos_users)[1],
        kos_first_name_index=_build_kos_name_related_indexes(kos_users)[2],
        overrides=SlackAuditOverrides(set(), set(), {}, {}),
    )

    assert matched is None
    assert source == "ambiguous_name"
    assert [candidate["id"] for candidate in ambiguous] == [1, 2]


def test_is_active_or_hiatus():
    assert is_active_or_hiatus({"status": "active"}) is True
    assert is_active_or_hiatus({"status": "hiatus"}) is True
    assert is_active_or_hiatus({"status": "inactive"}) is False


def test_email_variants_support_plus_addressing_and_kwartzlab_prefix():
    variants = _email_variants_for_matching("KwartzLab+Alex.Doe@kwartzlab.ca")
    assert variants == [
        "kwartzlab+alex.doe@kwartzlab.ca",
        "kwartzlab@kwartzlab.ca",
        "alex.doe@kwartzlab.ca",
    ]


def test_map_slack_user_supports_manual_override_by_user_id():
    kos_users = [
        {"id": 9, "email": "person@example.com", "first_name": "Person", "last_name": "One", "status": "active"},
    ]
    slack_user = {
        "id": "U999",
        "profile": {"email": "different@example.com", "real_name": "Unrelated Name"},
    }
    overrides = SlackAuditOverrides(
        ignored_slack_user_ids=set(),
        ignored_slack_emails=set(),
        manual_map_by_slack_user_id={"U999": 9},
        manual_map_by_slack_email={},
    )

    matched, source, ambiguous = _map_slack_user_to_kos(
        slack_user,
        kos_id_index=_build_kos_id_index(kos_users),
        kos_email_index=_build_kos_email_index(kos_users),
        kos_name_index=_build_kos_name_index(kos_users),
        kos_last_name_index=_build_kos_name_related_indexes(kos_users)[1],
        kos_first_name_index=_build_kos_name_related_indexes(kos_users)[2],
        overrides=overrides,
    )

    assert matched and matched["id"] == 9
    assert source == "manual_override"
    assert ambiguous == []


def test_map_slack_user_low_confidence_unique_last_name_variant_first():
    kos_users = [
        {"id": 7, "email": "dani@kwartzlab.ca", "first_name": "Dani", "last_name": "Ostashko", "status": "active"},
    ]
    slack_user = {
        "id": "U123",
        "profile": {"real_name": "Daniil Ostashko"},
    }

    matched, source, ambiguous = _map_slack_user_to_kos(
        slack_user,
        kos_id_index=_build_kos_id_index(kos_users),
        kos_email_index=_build_kos_email_index(kos_users),
        kos_name_index=_build_kos_name_index(kos_users),
        kos_last_name_index=_build_kos_name_related_indexes(kos_users)[1],
        kos_first_name_index=_build_kos_name_related_indexes(kos_users)[2],
        overrides=SlackAuditOverrides(set(), set(), {}, {}),
    )

    assert matched and matched["id"] == 7
    assert source == "low_confidence_unique_last_name"
    assert ambiguous == []


def test_map_slack_user_low_confidence_first_name_plus_last_initials():
    kos_users = [
        {
            "id": 8,
            "email": "alex@example.com",
            "first_name": "Alex",
            "last_name": "Anderson Brown",
            "status": "active",
        },
    ]
    slack_user = {
        "id": "U124",
        "profile": {"real_name": "Alex AB"},
    }

    matched, source, ambiguous = _map_slack_user_to_kos(
        slack_user,
        kos_id_index=_build_kos_id_index(kos_users),
        kos_email_index=_build_kos_email_index(kos_users),
        kos_name_index=_build_kos_name_index(kos_users),
        kos_last_name_index=_build_kos_name_related_indexes(kos_users)[1],
        kos_first_name_index=_build_kos_name_related_indexes(kos_users)[2],
        overrides=SlackAuditOverrides(set(), set(), {}, {}),
    )

    assert matched and matched["id"] == 8
    assert source == "low_confidence_last_initials"
    assert ambiguous == []


def test_normalize_email_is_case_insensitive():
    assert _normalize_email("User@Example.com") == "user@example.com"
