from utils.forms import applicant_data_to_dict


def _get_name_part(user: dict | None, keys: list[str]) -> str:
    if not user:
        return ""
    for key in keys:
        value = user.get(key)
        if value:
            value = str(value).strip()
            if value:
                return value
    return ""


def format_user_full_name(user: dict | None, *, fallback: str | None = None) -> str | None:
    first = _get_name_part(user, ["first_preferred", "preferred_first_name", "first_name", "first"])
    last = _get_name_part(user, ["last_preferred", "preferred_last_name", "last_name", "last"])
    full = " ".join(p for p in (first, last) if p).strip()
    return full or fallback


def format_submission_full_name(submission: dict | None) -> str | None:
    if not submission:
        return None
    data = submission.get("data", submission)
    label_values = applicant_data_to_dict(data)
    first = label_values.get("First Name") or ""
    last = label_values.get("Last Name") or ""
    full = " ".join(p for p in (first, last) if p).strip()
    return full or None
