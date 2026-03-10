import json
import logging
import re
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class KosIndexes:
    id_index: dict[int, dict]
    email_index: dict[str, list[dict]]
    name_index: dict[str, list[dict]]
    last_name_index: dict[str, list[dict]]
    first_name_index: dict[str, list[dict]]


@dataclass
class SlackAuditBuckets:
    mapped_rows: list[dict] = field(default_factory=list)
    low_confidence_rows: list[dict] = field(default_factory=list)
    unmapped_rows: list[dict] = field(default_factory=list)
    ambiguous_rows: list[dict] = field(default_factory=list)
    ignored_rows: list[dict] = field(default_factory=list)
    mapped_non_active_kos_rows: list[dict] = field(default_factory=list)


def load_slack_audit_config() -> SlackAuditConfig:
    include_deleted_raw = (getenv("SLACK_AUDIT_INCLUDE_DELETED", "false") or "false").strip().lower()
    return SlackAuditConfig(
        kos_api_base_url=getenv("KOS_API_BASE_URL", required=True),
        kos_api_token=getenv("KOS_API_TOKEN", required=True),
        kos_api_timeout_seconds=int(getenv("KOS_API_TIMEOUT_SECONDS", "10")),
        slack_bot_token=getenv("SLACK_BOT_TOKEN", required=True),
        include_deleted_slack_users=include_deleted_raw in {"1", "true", "yes", "y"},
        overrides_file=getenv("SLACK_AUDIT_OVERRIDES_FILE", "slack_audit_overrides.json")
        or "slack_audit_overrides.json",
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
        _normalize_email(str(item)) for item in payload.get("ignored_slack_emails", []) if _normalize_email(str(item))
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

    unique: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        if variant not in seen:
            seen.add(variant)
            unique.append(variant)

    return unique


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


def _build_kos_name_related_indexes(
    users: list[dict],
) -> tuple[dict[str, list[dict]], dict[str, list[dict]], dict[str, list[dict]]]:
    name_index: dict[str, list[dict]] = {}
    last_name_index: dict[str, list[dict]] = {}
    first_name_index: dict[str, list[dict]] = {}

    for user in users:
        first = _normalize_name(kos_api.get_user_first_name(user, default=""))
        last = _normalize_name(kos_api.get_user_last_name(user, default=""))

        if first:
            first_name_index.setdefault(first, []).append(user)
        if last:
            last_name_index.setdefault(last, []).append(user)

        full_name = " ".join(part for part in [first, last] if part)
        if full_name:
            name_index.setdefault(full_name, []).append(user)

    return name_index, last_name_index, first_name_index


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


def _load_kos_user_data(cfg: SlackAuditConfig) -> list[dict]:
    kos_client = kos_api.KosApiClient(
        base_url=cfg.kos_api_base_url,
        token=cfg.kos_api_token,
        timeout_seconds=cfg.kos_api_timeout_seconds,
    )
    kos_users = kos_client.list_users()
    print(f"Loaded {len(kos_users)} users from kOS.")
    return kos_users


def _load_kos_indexes(cfg: SlackAuditConfig) -> tuple[list[dict], KosIndexes]:
    kos_users = _load_kos_user_data(cfg)
    name_index, last_name_index, first_name_index = _build_kos_name_related_indexes(kos_users)
    indexes = KosIndexes(
        id_index=_build_kos_id_index(kos_users),
        email_index=_build_kos_email_index(kos_users),
        name_index=name_index,
        last_name_index=last_name_index,
        first_name_index=first_name_index,
    )
    return kos_users, indexes


def _load_slack_candidates(cfg: SlackAuditConfig) -> tuple[list[dict], list[dict]]:
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

    return slack_members, candidates


def _build_base_audit_row(slack_user: dict, *, slack_email: str, match_source: str) -> dict:
    return {
        "slack_user_id": slack_user.get("id"),
        "slack_name": (slack_user.get("profile") or {}).get("real_name") or slack_user.get("real_name"),
        "slack_display_name": (slack_user.get("profile") or {}).get("display_name"),
        "slack_email": slack_email,
        "slack_deleted": bool(slack_user.get("deleted")),
        "match_source": match_source,
    }


def _audit_single_slack_user(
    slack_user: dict,
    *,
    indexes: KosIndexes,
    overrides: SlackAuditOverrides,
) -> tuple[str, dict]:
    slack_user_id = str(slack_user.get("id") or "").strip()
    slack_email = _extract_slack_user_email(slack_user)
    if slack_user_id in overrides.ignored_slack_user_ids or slack_email in overrides.ignored_slack_emails:
        return (
            "ignored",
            {
                "slack_user_id": slack_user_id,
                "slack_email": slack_email,
                "reason": "static_ignore",
            },
        )

    matched, match_source, ambiguous_candidates = _map_slack_user_to_kos(
        slack_user,
        kos_id_index=indexes.id_index,
        kos_email_index=indexes.email_index,
        kos_name_index=indexes.name_index,
        kos_last_name_index=indexes.last_name_index,
        kos_first_name_index=indexes.first_name_index,
        overrides=overrides,
    )

    base_row = _build_base_audit_row(slack_user, slack_email=slack_email, match_source=match_source)
    if ambiguous_candidates:
        return (
            "ambiguous",
            {
                **base_row,
                "candidate_kos_users": [_safe_kos_identity(candidate) for candidate in ambiguous_candidates],
            },
        )
    if not matched:
        return "unmapped", base_row

    mapped_row = {
        **base_row,
        "kos_user_id": matched.get("id"),
        "kos_name": kos_api.get_user_full_name(matched, default="unknown"),
        "kos_email": matched.get("email"),
        "kos_status": matched.get("status"),
        "kos_is_active_or_hiatus": _is_kos_active_or_hiatus(matched),
    }
    if match_source.startswith("low_confidence"):
        return "low_confidence", mapped_row
    return "mapped", mapped_row


def _run_membership_audit(
    candidates: list[dict],
    *,
    indexes: KosIndexes,
    overrides: SlackAuditOverrides,
) -> SlackAuditBuckets:
    buckets = SlackAuditBuckets()

    for slack_user in candidates:
        row_type, row = _audit_single_slack_user(slack_user, indexes=indexes, overrides=overrides)
        if row_type == "ignored":
            buckets.ignored_rows.append(row)
            continue
        if row_type == "ambiguous":
            buckets.ambiguous_rows.append(row)
            continue
        if row_type == "unmapped":
            buckets.unmapped_rows.append(row)
            continue
        if row_type == "low_confidence":
            buckets.low_confidence_rows.append(row)
        else:
            buckets.mapped_rows.append(row)

        if not row["kos_is_active_or_hiatus"]:
            buckets.mapped_non_active_kos_rows.append(row)

    return buckets


def _print_audit_report(
    *,
    slack_members_count: int,
    candidates_count: int,
    buckets: SlackAuditBuckets,
) -> None:
    print("\nSlack audit summary:")
    print(
        json.dumps(
            {
                "slack_users_loaded": slack_members_count,
                "slack_users_considered": candidates_count,
                "mapped_to_kos": len(buckets.mapped_rows),
                "mapped_to_kos_low_confidence_review_needed": len(buckets.low_confidence_rows),
                "unmapped": len(buckets.unmapped_rows),
                "ambiguous": len(buckets.ambiguous_rows),
                "ignored": len(buckets.ignored_rows),
                "mapped_to_non_active_or_non_hiatus_kos_users": len(buckets.mapped_non_active_kos_rows),
            },
            indent=2,
            ensure_ascii=True,
        )
    )

    print("\nMapped Slack users whose kOS status is NOT active/hiatus:")
    print(json.dumps(buckets.mapped_non_active_kos_rows, indent=2, ensure_ascii=True))

    print("\nLow-confidence Slack -> kOS matches (manual review):")
    print(json.dumps(buckets.low_confidence_rows, indent=2, ensure_ascii=True))

    print("\nAmbiguous Slack -> kOS matches (manual review):")
    print(json.dumps(buckets.ambiguous_rows, indent=2, ensure_ascii=True))

    print("\nIgnored Slack users:")
    print(json.dumps(buckets.ignored_rows, indent=2, ensure_ascii=True))

    print("\nUnmapped Slack users:")
    print(json.dumps(buckets.unmapped_rows, indent=2, ensure_ascii=True))


def main() -> None:
    configure_logging()
    cfg = load_slack_audit_config()

    _, indexes = _load_kos_indexes(cfg)
    overrides = load_slack_audit_overrides(cfg.overrides_file)
    print(f"Loaded Slack audit overrides from {cfg.overrides_file}.")

    slack_members, candidates = _load_slack_candidates(cfg)
    buckets = _run_membership_audit(candidates, indexes=indexes, overrides=overrides)
    _print_audit_report(
        slack_members_count=len(slack_members),
        candidates_count=len(candidates),
        buckets=buckets,
    )


if __name__ == "__main__":
    main()
