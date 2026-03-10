import logging
import re

import services.kos_api as kos_api
from services.google_admin import (
    add_user_to_group,
    build_workspace_user_insert_body,
    create_workspace_user,
    generate_workspace_primary_email_candidates,
    list_workspace_recovery_email_index,
    list_workspace_user_emails,
)

logger = logging.getLogger(__name__)

LOCAL_PART_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")
ACTIVE_KOS_STATUSES = {"active", "hiatus"}


def collect_missing_workspace_users(
    kos_client,
    admin_service,
    *,
    workspace_domain: str,
) -> list[dict]:
    if not workspace_domain:
        return []

    users = kos_client.list_users()
    active_users = [user for user in users if _is_active_or_hiatus_user(user)]
    workspace_users = list_workspace_user_emails(
        admin_service,
        domain=workspace_domain,
    )
    recovery_index = list_workspace_recovery_email_index(
        admin_service,
        domain=workspace_domain,
    )

    normalized_workspace_index: dict[str, set[str]] = {}
    for workspace_email in workspace_users:
        normalized = _normalize_workspace_email_for_match(workspace_email, workspace_domain)
        if normalized:
            normalized_workspace_index.setdefault(normalized, set()).add(workspace_email)

    missing_rows: list[dict] = []
    for user in active_users:
        match = _resolve_workspace_match_for_precheck(
            user,
            workspace_domain=workspace_domain,
            workspace_users=workspace_users,
            normalized_workspace_index=normalized_workspace_index,
            recovery_index=recovery_index,
        )
        if match["workspace_exists"]:
            continue
        missing_rows.append(
            {
                "kos_user_id": user.get("id"),
                "kos_name": kos_api.get_user_full_name(user, default="unknown"),
                "kos_email": user.get("email"),
                "expected_workspace_email": match.get("expected_workspace_email"),
                "error": match.get("error"),
            }
        )

    missing_rows.sort(key=lambda row: (str(row.get("kos_name") or ""), int(row.get("kos_user_id") or 0)))
    return missing_rows


def build_onboarding_preview(
    kos_client,
    kos_user_id: int,
    *,
    workspace_domain: str,
    workspace_groups: list[str],
) -> dict:
    if not workspace_domain:
        return {"ok": False, "message": "GOOGLE_WORKSPACE_DOMAIN is not configured."}

    user = kos_client.get_user(kos_user_id)
    if not user:
        return {"ok": False, "message": f"No kOS user found for id {kos_user_id}."}

    try:
        user_insert_body = build_workspace_user_insert_body(
            user,
            domain=workspace_domain,
        )
    except ValueError as exc:
        return {"ok": False, "message": f"Cannot build workspace account payload: {exc}"}

    return {
        "ok": True,
        "kos_user_id": kos_user_id,
        "kos_name": kos_api.get_user_full_name(user, default="unknown"),
        "kos_email": user.get("email"),
        "workspace_primary_email": user_insert_body.get("primaryEmail"),
        "workspace_recovery_email": user_insert_body.get("recoveryEmail"),
        "workspace_groups": list(workspace_groups or []),
        "message": f"Prepared onboarding draft for kOS user {kos_user_id}.",
    }


def create_workspace_account_for_user(
    kos_client,
    admin_service,
    kos_user_id: int,
    *,
    workspace_domain: str,
    workspace_groups: list[str],
) -> dict:
    preview = build_onboarding_preview(
        kos_client,
        kos_user_id,
        workspace_domain=workspace_domain,
        workspace_groups=workspace_groups,
    )
    if not preview.get("ok"):
        return {"ok": False, "message": preview["message"]}

    user = kos_client.get_user(kos_user_id)
    user_insert_body = build_workspace_user_insert_body(
        user,
        domain=workspace_domain,
    )

    try:
        created_user = create_workspace_user(
            admin_service,
            user_insert_body=user_insert_body,
        )
    except Exception as exc:
        logger.exception("Failed to create Workspace user for kOS user id %s.", kos_user_id)
        return {
            "ok": False,
            "message": "Workspace account creation failed.",
            "error": str(exc),
        }

    group_results: list[dict[str, str]] = []
    for group in workspace_groups:
        try:
            add_user_to_group(
                admin_service,
                group_key=group,
                user_email=str(user_insert_body.get("primaryEmail") or ""),
            )
            group_results.append({"group": group, "status": "added"})
        except Exception as exc:
            logger.exception("Failed adding user %s to group %s.", user_insert_body.get("primaryEmail"), group)
            group_results.append({"group": group, "status": f"error:{exc}"})

    return {
        "ok": True,
        "message": f"Created Workspace account for kOS user {kos_user_id}.",
        "created_user": {
            "id": created_user.get("id"),
            "primaryEmail": created_user.get("primaryEmail"),
            "name": created_user.get("name"),
            "changePasswordAtNextLogin": created_user.get("changePasswordAtNextLogin"),
            "recoveryEmail": created_user.get("recoveryEmail"),
        },
        "group_results": group_results,
    }


def _is_active_or_hiatus_user(user: dict) -> bool:
    return str(user.get("status") or "").strip().lower() in ACTIVE_KOS_STATUSES


def _normalize_workspace_domain(domain: str) -> str:
    clean_domain = domain.strip().lstrip("@").lower()
    if "." not in clean_domain:
        clean_domain = f"{clean_domain}.ca"
    return clean_domain


def _normalize_workspace_email_for_match(email: str, workspace_domain: str) -> str:
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


def _resolve_workspace_match_for_precheck(
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
            normalized_candidate = _normalize_workspace_email_for_match(candidate, workspace_domain)
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
