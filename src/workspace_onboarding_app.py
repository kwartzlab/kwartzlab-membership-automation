import argparse
import json
import logging
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
    get_admin_directory_service,
)

logger = logging.getLogger(__name__)


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


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_cli_args(argv)
    runtime_options = resolve_runtime_options(args)

    configure_logging()
    cfg = load_workspace_onboarding_config()

    kos_client = kos_api.KosApiClient(
        base_url=cfg.kos_api_base_url,
        token=cfg.kos_api_token,
        timeout_seconds=cfg.kos_api_timeout_seconds,
    )
    admin_service = get_admin_directory_service(
        credentials_file=cfg.credentials_file,
        token_file=cfg.google_admin_token_file,
    )
    gmail_service: Optional[object] = None

    print("Workspace onboarding app ready. Enter a kOS user ID, or 'q' to quit.")
    if runtime_options.dry_run_account or runtime_options.dry_run_email:
        print(
            "Dry-run enabled:"
            f" account_creation={runtime_options.dry_run_account},"
            f" email_send={runtime_options.dry_run_email}"
        )

    while True:
        raw_user_id = input("kOS user ID> ").strip()
        if raw_user_id.lower() in {"q", "quit", "exit"}:
            print("Exiting.")
            return
        if not raw_user_id:
            continue
        if not raw_user_id.isdigit():
            print("Please enter a numeric user ID.")
            continue

        user_id = int(raw_user_id)
        user = kos_client.get_user(user_id)
        if not user:
            print(f"No user found for id {user_id}.")
            continue

        try:
            user_insert_body = build_workspace_user_insert_body(
                user,
                domain=cfg.google_workspace_domain,
            )
        except ValueError as exc:
            print(f"Cannot build workspace account payload: {exc}")
            continue

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

        account_created = False
        if runtime_options.dry_run_account:
            print("DRY RUN: Skipping Workspace account creation call.")
            print(json.dumps({"would_create": user_insert_body}, indent=2, ensure_ascii=True))
        else:
            if not _yes_no_prompt("Create this Google Workspace account now?", default=False):
                print("Skipped account creation.")
                continue

            try:
                created_user = create_workspace_user(
                    admin_service,
                    user_insert_body=user_insert_body,
                )
            except HttpError as exc:
                logger.exception("Failed to create Workspace user for kOS user id %s.", user_id)
                details = exc.content.decode("utf-8", errors="ignore") if getattr(exc, "content", None) else str(exc)
                print("Workspace account creation failed:")
                print(details)
                continue
            except Exception:
                logger.exception("Failed to create Workspace user for kOS user id %s.", user_id)
                print("Workspace account creation failed due to an unexpected error.")
                continue

            account_created = True
            print("Workspace account created:")
            print(json.dumps(_safe_created_user_response(created_user), indent=2, ensure_ascii=True))

        if cfg.google_workspace_groups:
            if runtime_options.dry_run_account:
                print("DRY RUN: Skipping Workspace group membership API calls.")
                print(
                    json.dumps(
                        {
                            "would_add_to_groups": cfg.google_workspace_groups,
                            "member": workspace_email,
                        },
                        indent=2,
                        ensure_ascii=True,
                    )
                )
            else:
                group_results: list[dict[str, str]] = []
                for group in cfg.google_workspace_groups:
                    try:
                        add_user_to_group(
                            admin_service,
                            group_key=group,
                            user_email=workspace_email,
                        )
                        group_results.append({"group": group, "status": "added"})
                    except HttpError as exc:
                        status_code = getattr(getattr(exc, "resp", None), "status", None)
                        if status_code == 409:
                            group_results.append({"group": group, "status": "already_member"})
                            continue
                        logger.exception(
                            "Failed adding workspace user %s to group %s for kOS user id %s.",
                            workspace_email,
                            group,
                            user_id,
                        )
                        details = (
                            exc.content.decode("utf-8", errors="ignore") if getattr(exc, "content", None) else str(exc)
                        )
                        group_results.append({"group": group, "status": f"error:{details}"})
                    except Exception:
                        logger.exception(
                            "Unexpected failure adding workspace user %s to group %s for kOS user id %s.",
                            workspace_email,
                            group,
                            user_id,
                        )
                        group_results.append({"group": group, "status": "error:unexpected"})
                print("Workspace group assignment results:")
                print(json.dumps(group_results, indent=2, ensure_ascii=True))

        recipient = str(user.get("email") or "").strip()
        if not recipient:
            print("No applicant email found in kOS profile, skipping send.")
            continue

        if runtime_options.dry_run_email:
            print(f"DRY RUN: Skipping email send to {recipient}.")
            continue

        if runtime_options.dry_run_account and not account_created:
            print("Note: account creation was skipped in dry-run mode; only email sending will be tested.")

        if not _yes_no_prompt(f"Send this email to {recipient} now?", default=True):
            print("Skipped email send.")
            continue

        try:
            if gmail_service is None:
                gmail_service = mailer.get_gmail_service(
                    credentials_file=cfg.credentials_file,
                    token_file=cfg.token_file,
                )
            message = mailer.build_group_html_message(
                to=recipient,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                from_name=mailer.MEMBERSHIP_GROUP_FROM_NAME,
                from_email=mailer.MEMBERSHIP_GROUP_FROM_EMAIL,
                reply_to=mailer.MEMBERSHIP_GROUP_REPLY_TO,
                bcc=mailer.MEMBERSHIP_GROUP_FROM_EMAIL,  # BCC self to have a record of sent emails
            )
            mailer.send_message(service=gmail_service, user_id=mailer.SENDER_USER_ID, message=message)
            print(f"Email sent to {recipient}.")
        except Exception:
            logger.exception("Failed to send workspace onboarding email for kOS user id %s.", user_id)
            print("Workspace account was created, but email sending failed.")


if __name__ == "__main__":
    main()
