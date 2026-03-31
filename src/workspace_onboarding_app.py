import argparse
import json
import logging
import re
from dataclasses import dataclass
from html import escape
from typing import Optional

from googleapiclient.errors import HttpError

import services.kos_api as kos_api
import services.mailer as mailer
from core.config import getenv
from core.logging_setup import configure_logging
from services.google_admin import (
    add_user_to_group,
    build_workspace_user_insert_body,
    create_workspace_user,
    generate_workspace_primary_email_candidates,
    get_admin_directory_service,
    list_workspace_recovery_email_index,
    list_workspace_user_emails,
    normalize_workspace_domain,
)
from utils.cli import yes_no_prompt

logger = logging.getLogger(__name__)
LOCAL_PART_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class WorkspaceOnboardingConfig:
    kos_api_base_url: str
    kos_api_token: str
    kos_api_timeout_seconds: int
    credentials_file: str
    token_file: str
    google_admin_token_file: str
    google_workspace_domain: str
    google_workspace_groups: list[str]


@dataclass(frozen=True)
class RuntimeOptions:
    dry_run_account: bool
    dry_run_email: bool


@dataclass(frozen=True)
class UserOnboardingDraft:
    user_id: int
    user: dict
    user_insert_body: dict
    workspace_email: str
    subject: str
    text_body: str
    html_body: str


def load_workspace_onboarding_config() -> WorkspaceOnboardingConfig:
    domain = getenv("GOOGLE_WORKSPACE_DOMAIN", required=True)
    groups_raw = getenv("GOOGLE_WORKSPACE_GROUPS", "") or ""
    groups = [item.strip() for item in groups_raw.replace(",", " ").split() if item.strip()]
    return WorkspaceOnboardingConfig(
        kos_api_base_url=getenv("KOS_API_BASE_URL", required=True),
        kos_api_token=getenv("KOS_API_TOKEN", required=True),
        kos_api_timeout_seconds=int(getenv("KOS_API_TIMEOUT_SECONDS", "10")),
        credentials_file=getenv("CREDENTIALS_FILE", "credentials.json"),
        token_file=getenv("TOKEN_FILE", "token.json"),
        google_admin_token_file=getenv("GOOGLE_ADMIN_TOKEN_FILE", "token_admin.json"),
        google_workspace_domain=domain,
        google_workspace_groups=groups,
    )


def parse_cli_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive kOS -> Google Workspace onboarding tool.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run both account creation and email sending.",
    )
    parser.add_argument(
        "--dry-run-account",
        action="store_true",
        help="Dry run account creation only.",
    )
    parser.add_argument(
        "--dry-run-email",
        action="store_true",
        help="Dry run email sending only.",
    )
    return parser.parse_args(argv)


def resolve_runtime_options(args: argparse.Namespace) -> RuntimeOptions:
    if args.dry_run:
        return RuntimeOptions(dry_run_account=True, dry_run_email=True)
    return RuntimeOptions(
        dry_run_account=bool(args.dry_run_account),
        dry_run_email=bool(args.dry_run_email),
    )


def _normalize_workspace_email_for_match(email: str, workspace_domain: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value:
        return ""

    local_part, domain_part = value.rsplit("@", 1)
    normalized_domain = normalize_workspace_domain(workspace_domain)
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


def _run_missing_workspace_account_precheck(
    *,
    cfg: WorkspaceOnboardingConfig,
    kos_client: kos_api.KosApiClient,
    admin_service: object,
) -> None:
    if not yes_no_prompt(
        "Check active/hiatus kOS users for missing matching Workspace accounts first?",
        default=False,
    ):
        return

    print("Running pre-check for users without matching Workspace accounts...")
    users = kos_client.list_users()
    active_users = [user for user in users if kos_api.is_active_or_hiatus(user)]
    print(f"Loaded {len(users)} users from kOS; active/hiatus considered: {len(active_users)}")

    workspace_users = list_workspace_user_emails(
        admin_service,
        domain=cfg.google_workspace_domain,
    )
    print(f"Loaded {len(workspace_users)} workspace users from Google Admin.")

    normalized_workspace_index: dict[str, set[str]] = {}
    for workspace_email in workspace_users:
        normalized = _normalize_workspace_email_for_match(workspace_email, cfg.google_workspace_domain)
        if normalized:
            normalized_workspace_index.setdefault(normalized, set()).add(workspace_email)

    recovery_index = list_workspace_recovery_email_index(
        admin_service,
        domain=cfg.google_workspace_domain,
    )
    print(f"Loaded {len(recovery_index)} unique recovery emails from Google Admin.")

    missing_rows: list[dict] = []
    for user in active_users:
        match = _resolve_workspace_match_for_precheck(
            user,
            workspace_domain=cfg.google_workspace_domain,
            workspace_users=workspace_users,
            normalized_workspace_index=normalized_workspace_index,
            recovery_index=recovery_index,
        )
        if match["workspace_exists"]:
            continue

        row = {
            "kos_user_id": user.get("id"),
            "kos_name": kos_api.get_user_full_name(user, default="unknown"),
            "kos_email": user.get("email"),
            "expected_workspace_email": match.get("expected_workspace_email"),
        }
        if match.get("error"):
            row["error"] = match["error"]
        missing_rows.append(row)

    print("\nPre-check summary:")
    print(
        json.dumps(
            {
                "active_or_hiatus_users_checked": len(active_users),
                "users_missing_matching_workspace_account": len(missing_rows),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    print("\nActive/hiatus users missing matching Workspace accounts:")
    print(json.dumps(missing_rows, indent=2, ensure_ascii=True))


def _build_workspace_welcome_email(
    user: dict,
    *,
    workspace_email: str,
    initial_password: str,
) -> tuple[str, str, str]:
    first_name = kos_api.get_user_first_name(user, default="there")
    full_name = kos_api.get_user_full_name(user, default="there")

    subject = "Your Kwartzlab Google Workspace account details"
    text_body = (
        f"Hi {first_name},\n\n"
        "Your Kwartzlab Google Workspace account has been created.\n\n"
        f"Username: {workspace_email}\n"
        f"Temporary password: {initial_password}\n\n"
        "For security, you will be required to change your password on first login.\n\n"
        "Please let us know if you have any issues.\n\n"
        "Welcome,\n"
        "Kwartzlab Membership Team"
    )

    html_body = f"""
        <p>Hi {escape(first_name)},</p>
        <p>Your Kwartzlab Google Workspace account has been created.</p>
        <p>
            <b>Name:</b> {escape(full_name)}<br/>
            <b>Username:</b> {escape(workspace_email)}<br/>
            <b>Temporary password:</b> {escape(initial_password)}
        </p>
        <p>For security, you will be required to change your password on first login.</p>
        <p>Please let us know if you have any issues.</p>
        <p><b>Kwartzlab Membership Team</b></p>
    """
    return subject, text_body, html_body


def _print_draft_review(
    user: dict,
    user_insert_body: dict,
    email_subject: str,
    text_body: str,
    workspace_groups: list[str],
) -> None:
    summary = {
        "kos_user_id": user.get("id"),
        "kos_name": kos_api.get_user_full_name(user, default="unknown"),
        "kos_email": user.get("email"),
        "workspace_primary_email": user_insert_body.get("primaryEmail"),
        "workspace_recovery_email": user_insert_body.get("recoveryEmail"),
        "change_password_at_next_login": user_insert_body.get("changePasswordAtNextLogin"),
        "workspace_groups": workspace_groups,
    }
    print("\n----- Review -----")
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    print("\n----- Draft Email Subject -----")
    print(email_subject)
    print("\n----- Draft Email Body -----")
    print(text_body)
    print("------------------\n")


def _safe_created_user_response(created: dict) -> dict:
    return {
        "id": created.get("id"),
        "primaryEmail": created.get("primaryEmail"),
        "name": created.get("name"),
        "changePasswordAtNextLogin": created.get("changePasswordAtNextLogin"),
        "recoveryEmail": created.get("recoveryEmail"),
    }


def _load_kos_client(cfg: WorkspaceOnboardingConfig) -> kos_api.KosApiClient:
    return kos_api.KosApiClient(
        base_url=cfg.kos_api_base_url,
        token=cfg.kos_api_token,
        timeout_seconds=cfg.kos_api_timeout_seconds,
    )


def _load_admin_service(cfg: WorkspaceOnboardingConfig) -> object:
    return get_admin_directory_service(
        credentials_file=cfg.credentials_file,
        token_file=cfg.google_admin_token_file,
    )


def _print_startup_banner(runtime_options: RuntimeOptions) -> None:
    print("Workspace onboarding app ready. Enter a kOS user ID, or 'q' to quit.")
    if runtime_options.dry_run_account or runtime_options.dry_run_email:
        print(
            "Dry-run enabled:"
            f" account_creation={runtime_options.dry_run_account},"
            f" email_send={runtime_options.dry_run_email}"
        )


def _resolve_next_user_id() -> tuple[bool, Optional[int]]:
    raw_user_id = input("kOS user ID> ").strip()
    if raw_user_id.lower() in {"q", "quit", "exit"}:
        print("Exiting.")
        return True, None
    if not raw_user_id:
        return False, None
    if not raw_user_id.isdigit():
        print("Please enter a numeric user ID.")
        return False, None
    return False, int(raw_user_id)


def _build_user_onboarding_draft(
    user_id: int,
    *,
    kos_client: kos_api.KosApiClient,
    cfg: WorkspaceOnboardingConfig,
) -> Optional[UserOnboardingDraft]:
    user = kos_client.get_user(user_id)
    if not user:
        print(f"No user found for id {user_id}.")
        return None

    try:
        user_insert_body = build_workspace_user_insert_body(
            user,
            domain=cfg.google_workspace_domain,
        )
    except ValueError as exc:
        print(f"Cannot build workspace account payload: {exc}")
        return None

    workspace_email = str(user_insert_body["primaryEmail"])
    initial_password = str(user_insert_body["password"])
    subject, text_body, html_body = _build_workspace_welcome_email(
        user,
        workspace_email=workspace_email,
        initial_password=initial_password,
    )
    _print_draft_review(
        user,
        user_insert_body,
        subject,
        text_body,
        cfg.google_workspace_groups,
    )
    return UserOnboardingDraft(
        user_id=user_id,
        user=user,
        user_insert_body=user_insert_body,
        workspace_email=workspace_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def _create_workspace_account(
    *,
    draft: UserOnboardingDraft,
    admin_service: object,
    runtime_options: RuntimeOptions,
) -> tuple[bool, bool]:
    if runtime_options.dry_run_account:
        print("DRY RUN: Skipping Workspace account creation call.")
        print(json.dumps({"would_create": draft.user_insert_body}, indent=2, ensure_ascii=True))
        return True, False

    if not yes_no_prompt("Create this Google Workspace account now?", default=False):
        print("Skipped account creation.")
        return False, False

    try:
        created_user = create_workspace_user(
            admin_service,
            user_insert_body=draft.user_insert_body,
        )
    except HttpError as exc:
        logger.exception("Failed to create Workspace user for kOS user id %s.", draft.user_id)
        details = exc.content.decode("utf-8", errors="ignore") if getattr(exc, "content", None) else str(exc)
        print("Workspace account creation failed:")
        print(details)
        return False, False
    except Exception:
        logger.exception("Failed to create Workspace user for kOS user id %s.", draft.user_id)
        print("Workspace account creation failed due to an unexpected error.")
        return False, False

    print("Workspace account created:")
    print(json.dumps(_safe_created_user_response(created_user), indent=2, ensure_ascii=True))
    return True, True


def _assign_workspace_groups(
    *,
    cfg: WorkspaceOnboardingConfig,
    draft: UserOnboardingDraft,
    admin_service: object,
    runtime_options: RuntimeOptions,
) -> None:
    if not cfg.google_workspace_groups:
        return

    if runtime_options.dry_run_account:
        print("DRY RUN: Skipping Workspace group membership API calls.")
        print(
            json.dumps(
                {
                    "would_add_to_groups": cfg.google_workspace_groups,
                    "member": draft.workspace_email,
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return

    group_results: list[dict[str, str]] = []
    for group in cfg.google_workspace_groups:
        try:
            add_user_to_group(
                admin_service,
                group_key=group,
                user_email=draft.workspace_email,
            )
            group_results.append({"group": group, "status": "added"})
        except HttpError as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 409:
                group_results.append({"group": group, "status": "already_member"})
                continue
            logger.exception(
                "Failed adding workspace user %s to group %s for kOS user id %s.",
                draft.workspace_email,
                group,
                draft.user_id,
            )
            details = exc.content.decode("utf-8", errors="ignore") if getattr(exc, "content", None) else str(exc)
            group_results.append({"group": group, "status": f"error:{details}"})
        except Exception:
            logger.exception(
                "Unexpected failure adding workspace user %s to group %s for kOS user id %s.",
                draft.workspace_email,
                group,
                draft.user_id,
            )
            group_results.append({"group": group, "status": "error:unexpected"})

    print("Workspace group assignment results:")
    print(json.dumps(group_results, indent=2, ensure_ascii=True))


def _send_welcome_email(
    *,
    cfg: WorkspaceOnboardingConfig,
    draft: UserOnboardingDraft,
    runtime_options: RuntimeOptions,
    account_created: bool,
    gmail_service: Optional[object],
) -> Optional[object]:
    recipient = str(draft.user.get("email") or "").strip()
    if not recipient:
        print("No applicant email found in kOS profile, skipping send.")
        return gmail_service

    if runtime_options.dry_run_email:
        print(f"DRY RUN: Skipping email send to {recipient}.")
        return gmail_service

    if runtime_options.dry_run_account and not account_created:
        print("Note: account creation was skipped in dry-run mode; only email sending will be tested.")

    if not yes_no_prompt(f"Send this email to {recipient} now?", default=True):
        print("Skipped email send.")
        return gmail_service

    try:
        if gmail_service is None:
            gmail_service = mailer.get_gmail_service(
                credentials_file=cfg.credentials_file,
                token_file=cfg.token_file,
            )
        message = mailer.build_group_html_message(
            to=recipient,
            subject=draft.subject,
            text_body=draft.text_body,
            html_body=draft.html_body,
            from_name=mailer.MEMBERSHIP_GROUP_FROM_NAME,
            from_email=mailer.MEMBERSHIP_GROUP_FROM_EMAIL,
            reply_to=mailer.MEMBERSHIP_GROUP_REPLY_TO,
            bcc=mailer.MEMBERSHIP_GROUP_FROM_EMAIL,  # BCC self to have a record of sent emails
        )
        mailer.send_message(service=gmail_service, user_id=mailer.SENDER_USER_ID, message=message)
        print(f"Email sent to {recipient}.")
    except Exception:
        logger.exception("Failed to send workspace onboarding email for kOS user id %s.", draft.user_id)
        print("Workspace account was created, but email sending failed.")

    return gmail_service


def _run_onboarding_loop(
    *,
    cfg: WorkspaceOnboardingConfig,
    runtime_options: RuntimeOptions,
    kos_client: kos_api.KosApiClient,
    admin_service: object,
) -> None:
    gmail_service: Optional[object] = None

    while True:
        should_exit, user_id = _resolve_next_user_id()
        if should_exit:
            return
        if user_id is None:
            continue

        draft = _build_user_onboarding_draft(
            user_id,
            kos_client=kos_client,
            cfg=cfg,
        )
        if not draft:
            continue

        should_continue, account_created = _create_workspace_account(
            draft=draft,
            admin_service=admin_service,
            runtime_options=runtime_options,
        )
        if not should_continue:
            continue

        _assign_workspace_groups(
            cfg=cfg,
            draft=draft,
            admin_service=admin_service,
            runtime_options=runtime_options,
        )

        gmail_service = _send_welcome_email(
            cfg=cfg,
            draft=draft,
            runtime_options=runtime_options,
            account_created=account_created,
            gmail_service=gmail_service,
        )


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_cli_args(argv)
    runtime_options = resolve_runtime_options(args)

    configure_logging()
    cfg = load_workspace_onboarding_config()
    kos_client = _load_kos_client(cfg)
    admin_service = _load_admin_service(cfg)

    _print_startup_banner(runtime_options)
    _run_missing_workspace_account_precheck(
        cfg=cfg,
        kos_client=kos_client,
        admin_service=admin_service,
    )
    _run_onboarding_loop(
        cfg=cfg,
        runtime_options=runtime_options,
        kos_client=kos_client,
        admin_service=admin_service,
    )


if __name__ == "__main__":
    main()
