import json
import logging
import re
from dataclasses import dataclass

from googleapiclient.errors import HttpError

import services.kos_api as kos_api
from core.config import getenv
from core.logging_setup import configure_logging
from services.google_admin import (
    add_user_to_group,
    generate_workspace_primary_email_candidates,
    get_admin_directory_service,
    has_member_in_group,
    list_group_member_emails,
    list_workspace_recovery_email_index,
    list_workspace_user_emails,
)

logger = logging.getLogger(__name__)
LOCAL_PART_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class WorkspaceAuditConfig:
    kos_api_base_url: str
    kos_api_token: str
    kos_api_timeout_seconds: int
    credentials_file: str
    google_admin_token_file: str
    google_workspace_domain: str
    google_workspace_groups: list[str]


@dataclass(frozen=True)
class WorkspaceDirectoryData:
    admin_service: object
    workspace_users: set[str]
    normalized_workspace_index: dict[str, set[str]]
    recovery_index: dict[str, set[str]]
    group_members: dict[str, set[str]]


def load_workspace_audit_config() -> WorkspaceAuditConfig:
    groups_raw = getenv("GOOGLE_WORKSPACE_GROUPS", "") or ""
    groups = [item.strip() for item in groups_raw.replace(",", " ").split() if item.strip()]
    return WorkspaceAuditConfig(
        kos_api_base_url=getenv("KOS_API_BASE_URL", required=True),
        kos_api_token=getenv("KOS_API_TOKEN", required=True),
        kos_api_timeout_seconds=int(getenv("KOS_API_TIMEOUT_SECONDS", "10")),
        credentials_file=getenv("CREDENTIALS_FILE", "credentials.json"),
        google_admin_token_file=getenv("GOOGLE_ADMIN_TOKEN_FILE", "token_admin.json"),
        google_workspace_domain=getenv("GOOGLE_WORKSPACE_DOMAIN", required=True),
        google_workspace_groups=groups,
    )


def _build_audit_result(user: dict, *, workspace_email: str, exists: bool, missing_groups: list[str]) -> dict:
    return {
        "kos_user_id": user.get("id"),
        "kos_name": kos_api.get_user_full_name(user, default="unknown"),
        "kos_email": user.get("email"),
        "workspace_email": workspace_email,
        "workspace_exists": exists,
        "missing_groups": missing_groups,
        "in_all_groups": exists and not missing_groups,
    }


def _is_active_user(user: dict) -> bool:
    return str(user.get("status") or "").strip().lower() in {"active", "hiatus"}


def _normalize_workspace_domain(domain: str) -> str:
    clean_domain = domain.strip().lstrip("@").lower()
    if "." not in clean_domain:
        clean_domain = f"{clean_domain}.ca"
    return clean_domain


def _normalize_email_for_match(email: str, workspace_domain: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value:
        return ""
    local_part, domain_part = value.rsplit("@", 1)
    normalized_domain = _normalize_workspace_domain(workspace_domain)
    if domain_part != normalized_domain:
        return ""
    normalized_local = LOCAL_PART_SANITIZE_PATTERN.sub("", local_part)
    if not normalized_local:
        return ""
    return f"{normalized_local}@{normalized_domain}"


def _yes_no_prompt(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{prompt} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _split_missing_group_results(
    rows: list[dict],
    configured_groups: list[str],
) -> tuple[list[dict], list[dict]]:
    full_missing = [row for row in rows if len(row.get("missing_groups", [])) == len(configured_groups)]
    partial_missing = [row for row in rows if 0 < len(row.get("missing_groups", [])) < len(configured_groups)]
    return full_missing, partial_missing


def _resolve_workspace_match(
    user: dict,
    *,
    workspace_domain: str,
    workspace_users: set[str],
    normalized_workspace_index: dict[str, set[str]],
    recovery_index: dict[str, set[str]],
) -> dict:
    try:
        workspace_email_candidates = generate_workspace_primary_email_candidates(user, workspace_domain)
    except ValueError:
        workspace_email_candidates = []

    expected_workspace_email = workspace_email_candidates[0] if workspace_email_candidates else None
    resolved_workspace_email = expected_workspace_email
    email_match_source = "generated"
    exists = False

    for candidate in workspace_email_candidates:
        if candidate.lower() in workspace_users:
            resolved_workspace_email = candidate
            exists = True
            if candidate != expected_workspace_email:
                email_match_source = "generated_variant"
            break

    if not exists and workspace_email_candidates:
        normalized_matches: set[str] = set()
        for candidate in workspace_email_candidates:
            normalized_candidate = _normalize_email_for_match(candidate, workspace_domain)
            if not normalized_candidate:
                continue
            normalized_matches.update(normalized_workspace_index.get(normalized_candidate, set()))
        if normalized_matches:
            resolved_workspace_email = sorted(normalized_matches)[0]
            exists = True
            email_match_source = "normalized_variant"

    if not exists:
        kos_email = str(user.get("email") or "").strip().lower()
        if kos_email:
            candidates = sorted(recovery_index.get(kos_email, set()))
            if candidates:
                resolved_workspace_email = candidates[0]
                exists = True
                email_match_source = "google_recovery_email"

    result = {
        "expected_workspace_email": expected_workspace_email,
        "workspace_email": resolved_workspace_email,
        "workspace_exists": exists,
        "email_match_source": email_match_source,
    }
    if not workspace_email_candidates:
        result["error"] = "missing_name_fields"
    return result


def _load_kos_user_data(cfg: WorkspaceAuditConfig) -> list[dict]:
    kos_client = kos_api.KosApiClient(
        base_url=cfg.kos_api_base_url,
        token=cfg.kos_api_token,
        timeout_seconds=cfg.kos_api_timeout_seconds,
    )
    users = kos_client.list_users()
    print(f"Loaded {len(users)} users from kOS.")
    return users


def _build_normalized_workspace_index(
    workspace_users: set[str],
    workspace_domain: str,
) -> dict[str, set[str]]:
    normalized_workspace_index: dict[str, set[str]] = {}
    for workspace_email in workspace_users:
        normalized = _normalize_email_for_match(workspace_email, workspace_domain)
        if normalized:
            normalized_workspace_index.setdefault(normalized, set()).add(workspace_email)
    return normalized_workspace_index


def _load_workspace_directory_data(cfg: WorkspaceAuditConfig) -> WorkspaceDirectoryData:
    admin_service = get_admin_directory_service(
        credentials_file=cfg.credentials_file,
        token_file=cfg.google_admin_token_file,
    )

    workspace_users = list_workspace_user_emails(
        admin_service,
        domain=cfg.google_workspace_domain,
    )
    print(f"Loaded {len(workspace_users)} workspace users from Google Admin.")

    normalized_workspace_index = _build_normalized_workspace_index(
        workspace_users,
        cfg.google_workspace_domain,
    )

    recovery_index = list_workspace_recovery_email_index(
        admin_service,
        domain=cfg.google_workspace_domain,
    )
    print(f"Loaded {len(recovery_index)} unique recovery emails from Google Admin.")

    group_members: dict[str, set[str]] = {}
    for group in cfg.google_workspace_groups:
        members = list_group_member_emails(admin_service, group_key=group)
        group_members[group] = members
        print(f"Loaded {len(members)} members for group {group}.")

    return WorkspaceDirectoryData(
        admin_service=admin_service,
        workspace_users=workspace_users,
        normalized_workspace_index=normalized_workspace_index,
        recovery_index=recovery_index,
        group_members=group_members,
    )


def _partition_users_by_status(users: list[dict]) -> tuple[list[dict], list[dict]]:
    active_users = [user for user in users if _is_active_user(user)]
    non_active_users = [user for user in users if not _is_active_user(user)]
    return active_users, non_active_users


def _audit_active_users(
    active_users: list[dict],
    *,
    cfg: WorkspaceAuditConfig,
    directory_data: WorkspaceDirectoryData,
) -> list[dict]:
    results: list[dict] = []

    for user in active_users:
        workspace_match = _resolve_workspace_match(
            user,
            workspace_domain=cfg.google_workspace_domain,
            workspace_users=directory_data.workspace_users,
            normalized_workspace_index=directory_data.normalized_workspace_index,
            recovery_index=directory_data.recovery_index,
        )

        missing_groups: list[str] = []
        if workspace_match["workspace_exists"]:
            resolved_workspace_email = str(workspace_match["workspace_email"] or "")
            for group in cfg.google_workspace_groups:
                if resolved_workspace_email.lower() not in directory_data.group_members[group]:
                    missing_groups.append(group)
            if missing_groups:
                verified_missing: list[str] = []
                for group in missing_groups:
                    if not has_member_in_group(
                        directory_data.admin_service,
                        group_key=group,
                        user_email=resolved_workspace_email,
                    ):
                        verified_missing.append(group)
                missing_groups = verified_missing
        else:
            missing_groups = list(cfg.google_workspace_groups)

        result = _build_audit_result(
            user,
            workspace_email=workspace_match["workspace_email"],
            exists=workspace_match["workspace_exists"],
            missing_groups=missing_groups,
        )
        result["expected_workspace_email"] = workspace_match.get("expected_workspace_email")
        result["email_match_source"] = workspace_match.get("email_match_source")
        if workspace_match.get("error"):
            result["error"] = workspace_match["error"]
        results.append(result)

    return results


def _audit_non_active_users(
    non_active_users: list[dict],
    *,
    cfg: WorkspaceAuditConfig,
    directory_data: WorkspaceDirectoryData,
) -> list[dict]:
    non_active_workspace_rows: list[dict] = []

    for user in non_active_users:
        workspace_match = _resolve_workspace_match(
            user,
            workspace_domain=cfg.google_workspace_domain,
            workspace_users=directory_data.workspace_users,
            normalized_workspace_index=directory_data.normalized_workspace_index,
            recovery_index=directory_data.recovery_index,
        )
        if not workspace_match["workspace_exists"]:
            continue
        row = {
            "kos_user_id": user.get("id"),
            "kos_name": kos_api.get_user_full_name(user, default="unknown"),
            "kos_email": user.get("email"),
            "kos_status": user.get("status"),
            "workspace_email": workspace_match["workspace_email"],
            "expected_workspace_email": workspace_match.get("expected_workspace_email"),
            "email_match_source": workspace_match.get("email_match_source"),
        }
        if workspace_match.get("error"):
            row["error"] = workspace_match["error"]
        non_active_workspace_rows.append(row)

    return non_active_workspace_rows


def _print_workspace_audit_report(
    *,
    results: list[dict],
    non_active_users_count: int,
    non_active_workspace_rows: list[dict],
    configured_groups: list[str],
) -> tuple[list[dict], list[dict]]:
    missing_email = [row for row in results if not row.get("workspace_exists")]
    missing_group_membership = [row for row in results if row.get("workspace_exists") and row.get("missing_groups")]
    missing_all_groups, missing_some_groups = _split_missing_group_results(
        missing_group_membership,
        configured_groups,
    )
    fully_ok = [row for row in results if row.get("in_all_groups")]

    print("\nAudit summary:")
    print(
        json.dumps(
            {
                "total_users_checked": len(results),
                "total_non_active_users_checked_for_workspace_access": non_active_users_count,
                "non_active_users_with_workspace_email": len(non_active_workspace_rows),
                "workspace_email_missing": len(missing_email),
                "missing_group_membership": len(missing_group_membership),
                "missing_all_configured_groups": len(missing_all_groups),
                "missing_some_groups": len(missing_some_groups),
                "fully_ok": len(fully_ok),
            },
            indent=2,
            ensure_ascii=True,
        )
    )

    print("\nUsers missing workspace email:")
    print(json.dumps(missing_email, indent=2, ensure_ascii=True))
    print("\nNon-active users who still have a workspace email:")
    print(json.dumps(non_active_workspace_rows, indent=2, ensure_ascii=True))
    print("\nUsers missing at least one group:")
    print(json.dumps(missing_group_membership, indent=2, ensure_ascii=True))

    return missing_all_groups, missing_some_groups


def _run_group_remediation(
    *,
    admin_service: object,
    missing_all_groups: list[dict],
) -> None:
    if not _yes_no_prompt("Add eligible users to their missing groups now?", default=False):
        print("Skipped group remediation.")
        return

    remediation_results: list[dict] = []
    for row in missing_all_groups:
        user_email = row.get("workspace_email")
        if not user_email:
            remediation_results.append(
                {
                    "workspace_email": None,
                    "status": "skipped_no_workspace_email",
                }
            )
            continue

        for group in row.get("missing_groups", []):
            try:
                add_user_to_group(
                    admin_service,
                    group_key=group,
                    user_email=user_email,
                )
                remediation_results.append(
                    {
                        "workspace_email": user_email,
                        "group": group,
                        "status": "added",
                    }
                )
            except HttpError as exc:
                status_code = getattr(getattr(exc, "resp", None), "status", None)
                if status_code == 409:
                    remediation_results.append(
                        {
                            "workspace_email": user_email,
                            "group": group,
                            "status": "already_member",
                        }
                    )
                    continue
                logger.exception("Failed adding %s to group %s during remediation.", user_email, group)
                details = exc.content.decode("utf-8", errors="ignore") if getattr(exc, "content", None) else str(exc)
                remediation_results.append(
                    {
                        "workspace_email": user_email,
                        "group": group,
                        "status": f"error:{details}",
                    }
                )
            except Exception:
                logger.exception("Unexpected error adding %s to group %s during remediation.", user_email, group)
                remediation_results.append(
                    {
                        "workspace_email": user_email,
                        "group": group,
                        "status": "error:unexpected",
                    }
                )

    print("\nGroup remediation results:")
    print(json.dumps(remediation_results, indent=2, ensure_ascii=True))


def main() -> None:
    configure_logging()
    cfg = load_workspace_audit_config()
    users = _load_kos_user_data(cfg)
    if not cfg.google_workspace_groups:
        print("No GOOGLE_WORKSPACE_GROUPS configured; only existence checks will be performed.")

    active_users, non_active_users = _partition_users_by_status(users)
    print(f"Active/hiatus users to audit: {len(active_users)}")
    print(f"Non-active users to audit for stale Workspace accounts: {len(non_active_users)}")

    directory_data = _load_workspace_directory_data(cfg)
    results = _audit_active_users(
        active_users,
        cfg=cfg,
        directory_data=directory_data,
    )

    non_active_workspace_rows = _audit_non_active_users(
        non_active_users,
        cfg=cfg,
        directory_data=directory_data,
    )
    missing_all_groups, missing_some_groups = _print_workspace_audit_report(
        results=results,
        non_active_users_count=len(non_active_users),
        non_active_workspace_rows=non_active_workspace_rows,
        configured_groups=cfg.google_workspace_groups,
    )

    if not cfg.google_workspace_groups:
        return

    if not missing_all_groups:
        print("\nNo users are missing all configured groups; no remediation prompt needed.")
        return

    print("\nUsers missing all configured groups (eligible for remediation):")
    print(json.dumps(missing_all_groups, indent=2, ensure_ascii=True))
    if missing_some_groups:
        print(
            f"Skipping {len(missing_some_groups)} users with partial missing groups "
            "(treated as intentional per your policy)."
        )

    _run_group_remediation(
        admin_service=directory_data.admin_service,
        missing_all_groups=missing_all_groups,
    )


if __name__ == "__main__":
    main()
