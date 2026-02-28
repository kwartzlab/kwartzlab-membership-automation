import pytest

import services.google_admin as google_admin


def test_generate_workspace_primary_email_uses_expected_format():
    user = {"first_preferred": "Jane", "last_name": "Doe"}
    email = google_admin.generate_workspace_primary_email(user, "kwartzlab")
    assert email == "jane.doe@kwartzlab.ca"


def test_generate_workspace_primary_email_normalizes_name_and_domain():
    user = {"first_name": "Renée", "last_name": "O'Conner-Smith"}
    email = google_admin.generate_workspace_primary_email(user, "@kwartzlab.ca")
    assert email == "renee.oconnersmith@kwartzlab.ca"


def test_generate_workspace_primary_email_candidates_include_variants():
    user = {"first_name": "Anne-Marie", "last_name": "O'Neil"}
    candidates = google_admin.generate_workspace_primary_email_candidates(user, "kwartzlab")
    assert "annemarie.oneil@kwartzlab.ca" in candidates
    assert "annemarieoneil@kwartzlab.ca" in candidates
    assert "anne.marie.o.neil@kwartzlab.ca" in candidates


def test_generate_workspace_primary_email_candidates_keep_last_name_hyphen_variant():
    user = {"first_name": "Jane", "last_name": "Doe-Smith"}
    candidates = google_admin.generate_workspace_primary_email_candidates(user, "kwartzlab")
    assert "jane.doesmith@kwartzlab.ca" in candidates
    assert "jane.doe-smith@kwartzlab.ca" in candidates


def test_build_workspace_user_insert_body_contains_core_fields():
    user = {
        "first_preferred": "Avery",
        "last_preferred": "Ng",
        "email": "avery@example.com",
    }
    payload = google_admin.build_workspace_user_insert_body(
        user,
        domain="kwartzlab",
        initial_password="TemporaryPass123",
    )

    assert payload["primaryEmail"] == "avery.ng@kwartzlab.ca"
    assert payload["password"] == "TemporaryPass123"
    assert payload["changePasswordAtNextLogin"] is True
    assert payload["recoveryEmail"] == "avery@example.com"
    assert payload["name"]["givenName"] == "Avery"
    assert payload["name"]["familyName"] == "Ng"


def test_build_workspace_user_insert_body_requires_names():
    user = {"email": "missing.names@example.com"}
    with pytest.raises(ValueError):
        google_admin.build_workspace_user_insert_body(user, domain="kwartzlab")


def test_add_user_to_group_calls_directory_api():
    calls = {}

    class MembersApi:
        def insert(self, groupKey, body):
            calls["groupKey"] = groupKey
            calls["body"] = body

            class Request:
                def execute(self):
                    return {"kind": "admin#directory#member"}

            return Request()

    class Service:
        def members(self):
            return MembersApi()

    response = google_admin.add_user_to_group(
        Service(),
        group_key="members@kwartzlab.ca",
        user_email="jane.doe@kwartzlab.ca",
    )
    assert calls["groupKey"] == "members@kwartzlab.ca"
    assert calls["body"]["email"] == "jane.doe@kwartzlab.ca"
    assert calls["body"]["role"] == "MEMBER"
    assert response["kind"] == "admin#directory#member"


def test_list_workspace_user_emails_handles_paging_and_domain_filter():
    pages = [
        {
            "users": [
                {"primaryEmail": "one@kwartzlab.ca"},
                {"primaryEmail": "external@example.com"},
            ],
            "nextPageToken": "p2",
        },
        {
            "users": [
                {"primaryEmail": "two@kwartzlab.ca"},
            ],
        },
    ]

    class UsersApi:
        def list(self, **kwargs):
            idx = 1 if kwargs.get("pageToken") == "p2" else 0

            class Request:
                def execute(self):
                    return pages[idx]

            return Request()

    class Service:
        def users(self):
            return UsersApi()

    emails = google_admin.list_workspace_user_emails(Service(), domain="kwartzlab.ca")
    assert emails == {"one@kwartzlab.ca", "two@kwartzlab.ca"}


def test_list_workspace_user_emails_accepts_short_domain():
    page = {
        "users": [
            {"primaryEmail": "one@kwartzlab.ca"},
            {"primaryEmail": "external@example.com"},
        ]
    }

    class UsersApi:
        def list(self, **kwargs):
            class Request:
                def execute(self):
                    return page

            return Request()

    class Service:
        def users(self):
            return UsersApi()

    emails = google_admin.list_workspace_user_emails(Service(), domain="kwartzlab")
    assert emails == {"one@kwartzlab.ca"}


def test_list_group_member_emails_handles_paging():
    pages = [
        {
            "members": [{"email": "a@kwartzlab.ca"}],
            "nextPageToken": "p2",
        },
        {
            "members": [{"email": "b@kwartzlab.ca"}],
        },
    ]

    class MembersApi:
        calls = []

        def list(self, **kwargs):
            self.calls.append(kwargs)
            idx = 1 if kwargs.get("pageToken") == "p2" else 0

            class Request:
                def execute(self):
                    return pages[idx]

            return Request()

    class Service:
        api = MembersApi()

        def members(self):
            return self.api

    service = Service()
    emails = google_admin.list_group_member_emails(service, group_key="members@kwartzlab.ca")
    assert emails == {"a@kwartzlab.ca", "b@kwartzlab.ca"}
    assert service.api.calls[0]["includeDerivedMembership"] is True


def test_has_member_in_group_uses_has_member_endpoint():
    class MembersApi:
        def hasMember(self, **kwargs):
            class Request:
                def execute(self):
                    return {"isMember": True}

            return Request()

    class Service:
        def members(self):
            return MembersApi()

    assert google_admin.has_member_in_group(
        Service(),
        group_key="members@kwartzlab.ca",
        user_email="jane.doe@kwartzlab.ca",
    )


def test_list_workspace_recovery_email_index():
    page = {
        "users": [
            {"primaryEmail": "one@kwartzlab.ca", "recoveryEmail": "one.personal@example.com"},
            {"primaryEmail": "two@kwartzlab.ca", "recoveryEmail": "shared@example.com"},
            {"primaryEmail": "three@kwartzlab.ca", "recoveryEmail": "shared@example.com"},
            {"primaryEmail": "external@example.com", "recoveryEmail": "skip@example.com"},
        ]
    }

    class UsersApi:
        def list(self, **kwargs):
            class Request:
                def execute(self):
                    return page

            return Request()

    class Service:
        def users(self):
            return UsersApi()

    index = google_admin.list_workspace_recovery_email_index(Service(), domain="kwartzlab")
    assert index["one.personal@example.com"] == {"one@kwartzlab.ca"}
    assert index["shared@example.com"] == {"two@kwartzlab.ca", "three@kwartzlab.ca"}
    assert "skip@example.com" not in index
