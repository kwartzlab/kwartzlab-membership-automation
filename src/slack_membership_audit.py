import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import services.kos_api as kos_api
from core.config import getenv
from core.logging_setup import configure_logging

logger = logging.getLogger(__name__)

NAME_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")
ACTIVE_KOS_STATUSES = {"active", "hiatus"}


@dataclass(frozen=True)
class SlackAuditConfig:
    kos_api_base_url: str
    kos_api_token: str
    kos_api_timeout_seconds: int
    slack_bot_token: str
    include_deleted_slack_users: bool
    overrides_file: str


@dataclass(frozen=True)
class SlackAuditOverrides:
    ignored_slack_user_ids: set[str]
    ignored_slack_emails: set[str]
    manual_map_by_slack_user_id: dict[str, int]
    manual_map_by_slack_email: dict[str, int]


def load_slack_audit_config() -> SlackAuditConfig:
    include_deleted_raw = (getenv("SLACK_AUDIT_INCLUDE_DELETED", "false") or "false").strip().lower()
    return SlackAuditConfig(
        kos_api_base_url=getenv("KOS_API_BASE_URL", required=True),
        kos_api_token=getenv("KOS_API_TOKEN", required=True),
        kos_api_timeout_seconds=int(getenv("KOS_API_TIMEOUT_SECONDS", "10")),
        slack_bot_token=getenv("SLACK_BOT_TOKEN", required=True),
        include_deleted_slack_users=include_deleted_raw in {"1", "true", "yes", "y"},
        overrides_file=getenv("SLACK_AUDIT_OVERRIDES_FILE", "slack_audit_overrides.json") or "slack_audit_overrides.json",
    )


def load_slack_audit_overrides(path: str) -> SlackAuditOverrides:
    file_path = Path(path)
    if not file_path.exists():
        return SlackAuditOverrides(
            ignored_slack_user_ids=set(),
            ignored_slack_emails=set(),
            manual_map_by_slack_user_id={},
            manual_map_by_slack_email={},
        )

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    ignored_ids = {str(item).strip() for item in payload.get("ignored_slack_user_ids", []) if str(item).strip()}
    ignored_emails = {
        _normalize_email(str(item))
        for item in payload.get("ignored_slack_emails", [])
        if _normalize_email(str(item))
    }

    by_user_id: dict[str, int] = {}
    by_email: dict[str, int] = {}
    for entry in payload.get("manual_mappings", []):
        if not isinstance(entry, dict):
            continue
        kos_user_id_raw = entry.get("kos_user_id")
        if kos_user_id_raw is None:
            continue
        try:
            kos_user_id = int(kos_user_id_raw)
        except (TypeError, ValueError):
            continue

        slack_user_id = str(entry.get("slack_user_id") or "").strip()
        if slack_user_id:
            by_user_id[slack_user_id] = kos_user_id

        slack_email = _normalize_email(str(entry.get("slack_email") or ""))
        if slack_email:
            by_email[slack_email] = kos_user_id

    return SlackAuditOverrides(
        ignored_slack_user_ids=ignored_ids,
        ignored_slack_emails=ignored_emails,
        manual_map_by_slack_user_id=by_user_id,
        manual_map_by_slack_email=by_email,
    )


def _normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if "@" not in email:
        return ""
    return email


def _email_variants_for_matching(value: str) -> list[str]:
    email = _normalize_email(value)
    if not email:
        return []
    local_part, domain = email.split("@", 1)
    variants = [email]

    if "+" in local_part:
        plus_base = local_part.split("+", 1)[0]
        if plus_base:
            variants.append(f"{plus_base}@{domain}")
        if local_part.startswith("kwartzlab+"):
            promoted = local_part.split("kwartzlab+", 1)[1]
            if promoted:
                variants.append(f"{promoted}@{domain}")

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        if variant not in seen:
            seen.add(variant)
            deduped.append(variant)
    return deduped


def _normalize_name(value: str) -> str:
    clean = NAME_SANITIZE_PATTERN.sub(" ", (value or "").strip().lower())
    clean = " ".join(clean.split())
    return clean


def _is_kos_active_or_hiatus(user: dict) -> bool:
    return str(user.get("status") or "").strip().lower() in ACTIVE_KOS_STATUSES


def _is_human_slack_user(slack_user: dict) -> bool:
    if slack_user.get("id") == "USLACKBOT":
        return False
    if bool(slack_user.get("is_bot")):
        return False
    if bool(slack_user.get("is_app_user")):
        return False
    return True


def _extract_slack_user_email(slack_user: dict) -> str:
    profile = slack_user.get("profile") or {}
    return _normalize_email(str(profile.get("email") or ""))


def _extract_slack_name_candidates(slack_user: dict) -> list[str]:
    profile = slack_user.get("profile") or {}
    names = [
        profile.get("real_name_normalized"),
        profile.get("real_name"),
        profile.get("display_name_normalized"),
        profile.get("display_name"),
        slack_user.get("real_name"),
        slack_user.get("name"),
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = _normalize_name(str(name or ""))
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates


def _build_kos_email_index(users: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for user in users:
        email = _normalize_email(str(user.get("email") or ""))
        if not email:
            continue
        index.setdefault(email, []).append(user)
    return index


def _build_kos_name_index(users: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for user in users:
        name = _normalize_name(kos_api.get_user_full_name(user, default=""))
        if not name:
            continue
        index.setdefault(name, []).append(user)
    return index


def _build_kos_id_index(users: list[dict]) -> dict[int, dict]:
    index: dict[int, dict] = {}
    for user in users:
        user_id = user.get("id")
        if isinstance(user_id, int):
            index[user_id] = user
    return index


def _build_kos_last_name_index(users: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for user in users:
        last = _normalize_name(kos_api.get_user_last_name(user, default=""))
        if not last:
            continue
        index.setdefault(last, []).append(user)
    return index


def _build_kos_first_name_index(users: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for user in users:
        first = _normalize_name(kos_api.get_user_first_name(user, default=""))
        if not first:
            continue
        index.setdefault(first, []).append(user)
    return index


def _safe_kos_identity(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "name": kos_api.get_user_full_name(user, default="unknown"),
        "email": user.get("email"),
        "status": user.get("status"),
    }


def _split_first_last(name: str) -> tuple[str, str]:
    tokens = [token for token in _normalize_name(name).split(" ") if token]
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], " ".join(tokens[1:])


def _first_name_loosely_matches(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if a.startswith(b) or b.startswith(a):
        return True
    return a[0] == b[0]


def _name_initials(value: str) -> str:
    tokens = [token for token in _normalize_name(value).split(" ") if token]
    return "".join(token[0] for token in tokens)


def _find_low_confidence_name_match(
    slack_user: dict,
    *,
    kos_last_name_index: dict[str, list[dict]],
    kos_first_name_index: dict[str, list[dict]],
) -> tuple[Optional[dict], str, list[dict]]:
    for name_candidate in _extract_slack_name_candidates(slack_user):
        slack_first, slack_last = _split_first_last(name_candidate)
        if not slack_first:
            continue

        if slack_last:
            last_matches = kos_last_name_index.get(slack_last, [])
            if len(last_matches) == 1:
                user = last_matches[0]
                kos_first = _normalize_name(kos_api.get_user_first_name(user, default=""))
                if _first_name_loosely_matches(slack_first, kos_first):
                    return user, "low_confidence_unique_last_name", []
            elif len(last_matches) > 1:
                possible = []
                for user in last_matches:
                    kos_first = _normalize_name(kos_api.get_user_first_name(user, default=""))
                    if _first_name_loosely_matches(slack_first, kos_first):
                        possible.append(user)
                if len(possible) == 1:
                    return possible[0], "low_confidence_first_name_variant", []
                if len(possible) > 1:
                    return None, "ambiguous_low_confidence", possible

        first_matches = kos_first_name_index.get(slack_first, [])
        if len(first_matches) == 1 and slack_last:
            user = first_matches[0]
            kos_last = _normalize_name(kos_api.get_user_last_name(user, default=""))
            kos_last_initials = _name_initials(kos_last)
            if kos_last_initials and (slack_last == kos_last_initials or kos_last_initials.startswith(slack_last)):
                return user, "low_confidence_last_initials", []
            if kos_last.startswith(slack_last[0]):
                return user, "low_confidence_last_initial", []

    return None, "unmatched", []


def _map_slack_user_to_kos(
    slack_user: dict,
    *,
    kos_id_index: dict[int, dict],
    kos_email_index: dict[str, list[dict]],
    kos_name_index: dict[str, list[dict]],
    kos_last_name_index: dict[str, list[dict]],
    kos_first_name_index: dict[str, list[dict]],
    overrides: SlackAuditOverrides,
) -> tuple[Optional[dict], str, list[dict]]:
    slack_user_id = str(slack_user.get("id") or "").strip()
    slack_email = _extract_slack_user_email(slack_user)

    manual_kos_user_id = overrides.manual_map_by_slack_user_id.get(slack_user_id)
    if manual_kos_user_id is None and slack_email:
        manual_kos_user_id = overrides.manual_map_by_slack_email.get(slack_email)
    if manual_kos_user_id is not None:
        manual_user = kos_id_index.get(manual_kos_user_id)
        if manual_user:
            return manual_user, "manual_override", []
        return None, "manual_override_missing_kos_user", []

    for email in _email_variants_for_matching(slack_email):
        email_matches = kos_email_index.get(email, [])
        if len(email_matches) == 1:
            if email == slack_email:
                return email_matches[0], "email_exact", []
            return email_matches[0], "email_variant", []
        if len(email_matches) > 1:
            return None, "ambiguous_email", email_matches

    for normalized_name in _extract_slack_name_candidates(slack_user):
        name_matches = kos_name_index.get(normalized_name, [])
        if len(name_matches) == 1:
            return name_matches[0], "name_exact", []
        if len(name_matches) > 1:
            return None, "ambiguous_name", name_matches

    return _find_low_confidence_name_match(
        slack_user,
        kos_last_name_index=kos_last_name_index,
        kos_first_name_index=kos_first_name_index,
    )


def list_slack_users(slack_bot_token: str) -> list[dict]:
    client = WebClient(token=slack_bot_token)
    members: list[dict] = []
    cursor: Optional[str] = None

    while True:
        try:
            response = client.users_list(limit=200, cursor=cursor)
        except SlackApiError:
            logger.exception("Failed to fetch users_list from Slack API.")
            raise

        members.extend(response.get("members", []))
        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return members


def main() -> None:
    configure_logging()
    cfg = load_slack_audit_config()

    kos_client = kos_api.KosApiClient(
        base_url=cfg.kos_api_base_url,
        token=cfg.kos_api_token,
        timeout_seconds=cfg.kos_api_timeout_seconds,
    )
    kos_users = kos_client.list_users()
    kos_id_index = _build_kos_id_index(kos_users)
    kos_email_index = _build_kos_email_index(kos_users)
    kos_name_index = _build_kos_name_index(kos_users)
    kos_last_name_index = _build_kos_last_name_index(kos_users)
    kos_first_name_index = _build_kos_first_name_index(kos_users)
    print(f"Loaded {len(kos_users)} users from kOS.")
    overrides = load_slack_audit_overrides(cfg.overrides_file)
    print(f"Loaded Slack audit overrides from {cfg.overrides_file}.")

    slack_members = list_slack_users(cfg.slack_bot_token)
    print(f"Loaded {len(slack_members)} users from Slack.")

    candidates: list[dict] = []
    for user in slack_members:
        if not _is_human_slack_user(user):
            continue
        if not cfg.include_deleted_slack_users and bool(user.get("deleted")):
            continue
        candidates.append(user)
    print(f"Slack users considered for audit: {len(candidates)}")

    mapped_rows: list[dict] = []
    low_confidence_rows: list[dict] = []
    unmapped_rows: list[dict] = []
    ambiguous_rows: list[dict] = []
    ignored_rows: list[dict] = []
    mapped_non_active_kos_rows: list[dict] = []

    for slack_user in candidates:
        slack_user_id = str(slack_user.get("id") or "").strip()
        slack_email = _extract_slack_user_email(slack_user)
        if slack_user_id in overrides.ignored_slack_user_ids or slack_email in overrides.ignored_slack_emails:
            ignored_rows.append(
                {
                    "slack_user_id": slack_user_id,
                    "slack_email": slack_email,
                    "reason": "static_ignore",
                }
            )
            continue

        matched, match_source, ambiguous_candidates = _map_slack_user_to_kos(
            slack_user,
            kos_id_index=kos_id_index,
            kos_email_index=kos_email_index,
            kos_name_index=kos_name_index,
            kos_last_name_index=kos_last_name_index,
            kos_first_name_index=kos_first_name_index,
            overrides=overrides,
        )

        base_row = {
            "slack_user_id": slack_user.get("id"),
            "slack_name": (slack_user.get("profile") or {}).get("real_name") or slack_user.get("real_name"),
            "slack_display_name": (slack_user.get("profile") or {}).get("display_name"),
            "slack_email": slack_email,
            "slack_deleted": bool(slack_user.get("deleted")),
            "match_source": match_source,
        }

        if ambiguous_candidates:
            ambiguous_rows.append(
                {
                    **base_row,
                    "candidate_kos_users": [_safe_kos_identity(candidate) for candidate in ambiguous_candidates],
                }
            )
            continue

        if not matched:
            unmapped_rows.append(base_row)
            continue

        mapped_row = {
            **base_row,
            "kos_user_id": matched.get("id"),
            "kos_name": kos_api.get_user_full_name(matched, default="unknown"),
            "kos_email": matched.get("email"),
            "kos_status": matched.get("status"),
            "kos_is_active_or_hiatus": _is_kos_active_or_hiatus(matched),
        }
        if match_source.startswith("low_confidence"):
            low_confidence_rows.append(mapped_row)
        else:
            mapped_rows.append(mapped_row)
        if not mapped_row["kos_is_active_or_hiatus"]:
            mapped_non_active_kos_rows.append(mapped_row)

    print("\nSlack audit summary:")
    print(
        json.dumps(
            {
                "slack_users_loaded": len(slack_members),
                "slack_users_considered": len(candidates),
                "mapped_to_kos": len(mapped_rows),
                "mapped_to_kos_low_confidence_review_needed": len(low_confidence_rows),
                "unmapped": len(unmapped_rows),
                "ambiguous": len(ambiguous_rows),
                "ignored": len(ignored_rows),
                "mapped_to_non_active_or_non_hiatus_kos_users": len(mapped_non_active_kos_rows),
            },
            indent=2,
            ensure_ascii=True,
        )
    )

    print("\nMapped Slack users whose kOS status is NOT active/hiatus:")
    print(json.dumps(mapped_non_active_kos_rows, indent=2, ensure_ascii=True))

    print("\nLow-confidence Slack -> kOS matches (manual review):")
    print(json.dumps(low_confidence_rows, indent=2, ensure_ascii=True))

    print("\nAmbiguous Slack -> kOS matches (manual review):")
    print(json.dumps(ambiguous_rows, indent=2, ensure_ascii=True))

    print("\nIgnored Slack users:")
    print(json.dumps(ignored_rows, indent=2, ensure_ascii=True))

    print("\nUnmapped Slack users:")
    print(json.dumps(unmapped_rows, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
