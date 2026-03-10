import pytest

from utils.names import format_submission_full_name, format_user_full_name


@pytest.mark.parametrize(
    "user, fallback, expected",
    [
        # Full name from preferred fields
        ({"first_preferred": "Alice", "last_preferred": "Smith"}, None, "Alice Smith"),
        # Falls back through field priority
        ({"first_name": "Bob", "last_name": "Jones"}, None, "Bob Jones"),
        ({"first": "Carol", "last": "Lee"}, None, "Carol Lee"),
        # first_preferred wins over first_name
        ({"first_preferred": "Dave", "first_name": "David", "last_name": "Kim"}, None, "Dave Kim"),
        # Only first name
        ({"first_preferred": "Eve"}, None, "Eve"),
        # Only last name
        ({"last_name": "Fox"}, None, "Fox"),
        # None user returns fallback
        (None, "Applicant", "Applicant"),
        (None, None, None),
        # Empty user returns fallback
        ({}, "Applicant", "Applicant"),
        ({}, None, None),
        # Whitespace-only values are skipped
        ({"first_preferred": "  ", "first_name": "Grace", "last_name": "Hall"}, None, "Grace Hall"),
    ],
)
def test_format_user_full_name(user, fallback, expected):
    assert format_user_full_name(user, fallback=fallback) == expected


def _make_field(label, value):
    return {"label": label, "value": value}


@pytest.mark.parametrize(
    "submission, expected",
    [
        # Nested under "data" key (standard kOS shape)
        (
            {"data": {"1": _make_field("First Name", "Alice"), "2": _make_field("Last Name", "Smith")}},
            "Alice Smith",
        ),
        # Flat dict (no "data" wrapper)
        (
            {"1": _make_field("First Name", "Bob"), "2": _make_field("Last Name", "Jones")},
            "Bob Jones",
        ),
        # Preferred name fields override plain first/last
        (
            {
                "data": {
                    "1": _make_field("First Name", "Carol"),
                    "2": _make_field("Last Name", "Lee"),
                    "3": _make_field("Preferred First Name", "Caz"),
                }
            },
            "Caz Lee",
        ),
        # None submission
        (None, None),
        # Missing name fields
        ({"data": {"1": _make_field("Email Address", "x@example.com")}}, None),
    ],
)
def test_format_submission_full_name(submission, expected):
    assert format_submission_full_name(submission) == expected
