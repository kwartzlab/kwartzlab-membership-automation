import asyncio
import json
import logging
import re

from services.workspace_onboarding import (
    build_onboarding_preview,
    build_reset_preview,
    reset_workspace_account_password,
)
from slack.slack_handlers.onboarding_dm import handle_onboarding_dm_command
from slack.slack_handlers.user_resolver import resolve_kos_user_id
from slack.slack_handlers.utils import get_actor_user_id, get_admin_service

logger = logging.getLogger(__name__)

_USER_ARG_PATTERN = re.compile(r"(<@[A-Z0-9]+>|\d+)", re.IGNORECASE)


def email_dm_help_text() -> str:
    return (
        "Email/Workspace DM commands:\n"
        "- `check emails`: list active/hiatus kOS users missing Workspace accounts\n"
        "- `create email <kos_user_id|@user>`: preview and create a Workspace account\n"
        "- `reset password <kos_user_id|@user>`: preview and reset a user's Workspace password"
    )


async def handle_email_dm_command(text: str, *, user_id: str, say, cfg, runtime) -> bool:
    lowered = text.lower().strip()

    if lowered in {"check emails", "check email"}:
        return await handle_onboarding_dm_command(
            "onboard missing",
            user_id=user_id,
            say=say,
            cfg=cfg,
            runtime=runtime,
        )

    if re.match(r"create email\s+\S", lowered):
        arg = _USER_ARG_PATTERN.search(text)
        if not arg:
            await say("Usage: `create email <kos_user_id>` or `create email @user`")
            return True
        if not cfg.google_workspace_domain:
            await say("Google Workspace domain is not configured.")
            return True
        kos_user_id, error = await resolve_kos_user_id(arg.group(1), runtime=runtime)
        if error:
            await say(error)
            return True
        preview = await asyncio.to_thread(
            build_onboarding_preview,
            runtime.kos_api_client,
            kos_user_id,
            workspace_domain=cfg.google_workspace_domain,
            workspace_groups=list(cfg.google_workspace_groups or []),
        )
        if not preview["ok"]:
            await say(preview["message"])
            return True
        await say(blocks=_build_preview_blocks(preview, user_id), text=preview["message"])
        return True

    if re.match(r"reset password\s+\S", lowered) or re.match(r"reset email\s+\S", lowered):
        arg = _USER_ARG_PATTERN.search(text)
        if not arg:
            await say("Usage: `reset password <kos_user_id>` or `reset password @user`")
            return True
        if not cfg.google_workspace_domain:
            await say("Google Workspace domain is not configured.")
            return True
        kos_user_id, error = await resolve_kos_user_id(arg.group(1), runtime=runtime)
        if error:
            await say(error)
            return True
        preview = await asyncio.to_thread(
            build_reset_preview,
            runtime.kos_api_client,
            get_admin_service(cfg),
            kos_user_id,
            workspace_domain=cfg.google_workspace_domain,
        )
        if not preview["ok"]:
            await say(preview["message"])
            return True
        await say(blocks=_build_reset_confirm_blocks(preview, user_id), text=preview["message"])
        return True

    if lowered.startswith("check email") or lowered.startswith("create email") or lowered.startswith("reset"):
        await say("Unknown email command.\n" + email_dm_help_text())
        return True

    return False


def register_email_dm_handlers(app, cfg, runtime):
    @app.action("dm_reset_password_confirm")
    async def handle_dm_reset_password_confirm(ack, body, respond):
        await ack()
        actor_user_id = get_actor_user_id(body)
        if actor_user_id not in runtime.cache_manager.authorized_users:
            await respond(replace_original=False, text="You are not authorized to reset Workspace passwords.")
            return

        try:
            payload = json.loads((body.get("actions") or [{}])[0].get("value", "{}"))
            request_user_id = str(payload.get("request_user_id") or "")
            kos_user_id = int(payload.get("kos_user_id"))
        except Exception:
            await respond(replace_original=True, text="Could not parse reset payload.")
            return

        if request_user_id and actor_user_id != request_user_id:
            await respond(replace_original=True, text="This reset action is assigned to a different user.")
            return

        result = await asyncio.to_thread(
            reset_workspace_account_password,
            runtime.kos_api_client,
            get_admin_service(cfg),
            kos_user_id,
            workspace_domain=cfg.google_workspace_domain,
            gmail_service=runtime.mailer,
        )
        await respond(replace_original=True, text=result["message"], blocks=_build_reset_result_blocks(result))

    @app.action("dm_cancel")
    async def handle_dm_cancel(ack, respond):
        await ack()
        await respond(delete_original=True)


def _build_preview_blocks(preview: dict, request_user_id: str) -> list[dict]:
    groups = preview.get("workspace_groups") or []
    groups_text = ", ".join(f"`{g.split('@')[0]}`" for g in groups) if groups else "none"
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{preview.get('kos_name') or 'Unknown'} (kOS #{preview.get('kos_user_id')})",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Workspace email*\n{preview.get('workspace_primary_email') or 'n/a'}"},
                {"type": "mrkdwn", "text": f"*kOS email*\n{preview.get('kos_email') or 'none'}"},
                {"type": "mrkdwn", "text": f"*Recovery email*\n{preview.get('workspace_recovery_email') or 'none'}"},
                {"type": "mrkdwn", "text": f"*Groups*\n{groups_text}"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Create Account"},
                    "action_id": "dm_onboard_create",
                    "value": json.dumps(
                        {
                            "kos_user_id": preview.get("kos_user_id"),
                            "request_user_id": request_user_id,
                        },
                        ensure_ascii=True,
                    ),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "dm_cancel",
                    "value": "cancel",
                },
            ],
        },
    ]


def _build_reset_confirm_blocks(preview: dict, request_user_id: str) -> list[dict]:
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{preview.get('kos_name') or 'Unknown'} (kOS #{preview.get('kos_user_id')})",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Workspace account*\n{preview.get('workspace_email') or 'unknown'}"},
                {"type": "mrkdwn", "text": f"*kOS email*\n{preview.get('kos_email') or 'none'}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":warning: Resetting will generate a new password and email credentials to the user.",
                }
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Reset Password"},
                    "action_id": "dm_reset_password_confirm",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Reset password?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": f"This will reset the Workspace password for *{preview.get('workspace_email')}* and"
                            f" email the new credentials to the user.",
                        },
                        "confirm": {"type": "plain_text", "text": "Reset"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                    "value": json.dumps(
                        {
                            "kos_user_id": preview.get("kos_user_id"),
                            "request_user_id": request_user_id,
                        },
                        ensure_ascii=True,
                    ),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "dm_cancel",
                    "value": "cancel",
                },
            ],
        },
    ]


def _build_reset_result_blocks(result: dict) -> list[dict]:
    if not result.get("ok"):
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":x: {result.get('message', 'Password reset failed.')}"},
            }
        ]
        if result.get("error"):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```{result['error']}```"}})
        return blocks

    email_result = result.get("email_result", {})
    if email_result.get("ok"):
        email_line = f":envelope: New credentials emailed to {email_result.get('recipient')}"
    elif email_result.get("reason") == "no_gmail_service":
        email_line = ":warning: Credentials email not sent (no Gmail service configured)"
    elif email_result.get("reason") == "no_kos_email":
        email_line = ":warning: Credentials email not sent (user has no kOS email)"
    else:
        email_line = f":x: Credentials email failed: {email_result.get('reason', 'unknown error')}"

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *Password reset*\n*Workspace:*"
                f" {result.get('workspace_email') or 'unknown'}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": email_line},
        },
    ]
