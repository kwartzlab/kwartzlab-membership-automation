import services.kos_api as kos_api


def test_get_user_first_name_prefers_preferred():
    user = {
        "first_preferred": "Avery",
        "preferred_first_name": "Alt",
        "first_name": "Legal",
    }
    assert kos_api.get_user_first_name(user) == "Avery"


def test_get_user_last_name_falls_back():
    user = {
        "last_name": "Doe",
    }
    assert kos_api.get_user_last_name(user) == "Doe"


def test_get_user_full_name_handles_missing_names():
    assert kos_api.get_user_full_name({}, default="Applicant") == "Applicant"
