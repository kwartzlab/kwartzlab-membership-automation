import asyncio
import json
import logging
import re

from services.google_admin import get_workspace_user_by_email
from services.workspace_onboarding import (
    build_onboarding_preview,
    collect_missing_workspace_users,
    create_workspace_account_for_user,
)
from slack.slack_handlers.user_resolver import resolve_kos_user_id
from slack.slack_handlers.utils import get_actor_user_id, get_admin_service

logger = logging.getLogger(__name__)

MAX_MISSING_RESULTS = 15


def onboarding_help_text() -> str:
    return (
        "Onboarding DM commands:\n"
        "- `onboard missing` or `onboard list`: show active/hiatus users missing Workspace accounts\n"
        "- `onboard <kos_user_id|@user>`: preview and confirm Workspace account creation for one user\n"
        "- `help`: show this message"
    )


async def handle_onboarding_dm_command(text: str, *, user_id: str, say, cfg, runtime) -> bool:
    lowered = text.lower().strip()

    if lowered in {"onboard missing", "onboard list"}:
        await say("Running onboarding pre-check for users missing Workspace accounts...")
        rows = await asyncio.to_thread(
            collect_missing_workspace_users,
            runtime.kos_api_client,
            get_admin_service(cfg),
            workspace_domain=cfg.google_workspace_domain,
        )
        await say(blocks=_build_missing_accounts_blocks(rows), text=_missing_accounts_summary_text(rows))
        return True

    match = re.match(r"(?i)^onboard\s+(\S+)", text.strip())
    if match and not lowered.startswith("onboard missing") and not lowered.startswith("onboard list"):
        kos_user_id, error = await resolve_kos_user_id(match.group(1), runtime=runtime)
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

    if lowered.startswith("onboard"):
        await say("Unknown onboarding command.\n" + onboarding_help_text())
        return True

    return False


def register_onboarding_dm_handlers(app, cfg, runtime):
    @app.action("dm_onboard_prepare")
    async def handle_dm_onboard_prepare(ack, body, respond):
        await ack()
        actor_user_id = get_actor_user_id(body)
        if actor_user_id not in runtime.cache_manager.authorized_users:
            await respond(replace_original=False, text="You are not authorized to run onboarding workflows.")
            return

        try:
            payload = json.loads((body.get("actions") or [{}])[0].get("value", "{}"))
            kos_user_id = int(payload.get("kos_user_id"))
        except Exception:
            await respond(replace_original=False, text="Could not parse onboarding request.")
            return

        preview = await asyncio.to_thread(
            build_onboarding_preview,
            runtime.kos_api_client,
            kos_user_id,
            workspace_domain=cfg.google_workspace_domain,
            workspace_groups=list(cfg.google_workspace_groups or []),
        )
        if not preview["ok"]:
            await respond(replace_original=False, text=preview["message"])
            return

        workspace_email = preview.get("workspace_primary_email")
        if workspace_email:
            existing = await asyncio.to_thread(
                get_workspace_user_by_email, get_admin_service(cfg), user_email=workspace_email
            )
            if existing:
                await respond(
                    replace_original=False,
                    text=f"A Workspace account already exists for {workspace_email}.",
                )
                return

        await respond(
            replace_original=False,
            text=preview["message"],
            blocks=_build_preview_blocks(preview, actor_user_id),
        )

    @app.action("dm_onboard_create")
    async def handle_dm_onboard_create(ack, body, respond):
        await ack()
        actor_user_id = get_actor_user_id(body)
        if actor_user_id not in runtime.cache_manager.authorized_users:
            await respond(replace_original=True, text="You are not authorized to run onboarding workflows.")
            return

        try:
            payload = json.loads((body.get("actions") or [{}])[0].get("value", "{}"))
            request_user_id = str(payload.get("request_user_id") or "")
            kos_user_id = int(payload.get("kos_user_id"))
        except Exception:
            await respond(replace_original=True, text="Could not parse onboarding payload.")
            return

        if request_user_id and actor_user_id != request_user_id:
            await respond(replace_original=True, text="This onboarding action is assigned to a different user.")
            return

        result = await asyncio.to_thread(
            create_workspace_account_for_user,
            runtime.kos_api_client,
            get_admin_service(cfg),
            kos_user_id,
            workspace_domain=cfg.google_workspace_domain,
            workspace_groups=list(cfg.google_workspace_groups or []),
            gmail_service=runtime.mailer,
        )
        await respond(replace_original=True, text=result["message"], blocks=_build_create_result_blocks(result))


def _missing_accounts_summary_text(rows: list[dict]) -> str:
    return f"Users missing matching Workspace accounts: {len(rows)}"


def _build_missing_accounts_blocks(rows: list[dict]) -> list[dict]:
    if not rows:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "No active/hiatus users are missing matching Workspace accounts."},
            }
        ]

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Users missing matching Workspace accounts:* {len(rows)}",
            },
        }
    ]

    for row in rows[:MAX_MISSING_RESULTS]:
        kos_user_id = row.get("kos_user_id")
        name = row.get("kos_name") or "unknown"
        kos_email = row.get("kos_email") or "none"
        expected = row.get("expected_workspace_email") or "n/a"
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{name}* (kOS `{kos_user_id}`)\nkOS email: `{kos_email}`\nExpected workspace: `{expected}`"
                    ),
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Prepare Onboard"},
                    "action_id": "dm_onboard_prepare",
                    "value": json.dumps({"kos_user_id": kos_user_id}, ensure_ascii=True),
                },
            }
        )

    remaining = len(rows) - MAX_MISSING_RESULTS
    if remaining > 0:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Showing first {MAX_MISSING_RESULTS}. {remaining} more users omitted.",
                    }
                ],
            }
        )

    return blocks


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


def _build_create_result_blocks(result: dict) -> list[dict]:
    if not result.get("ok"):
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":x: {result.get('message', 'Failed to create account.')}"},
            }
        ]
        if result.get("error"):
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{result['error']}```"},
                }
            )
        return blocks

    created_user = result.get("created_user", {})
    group_results = result.get("group_results", [])
    email_result = result.get("email_result", {})

    group_lines = []
    for g in group_results:
        status = g.get("status", "unknown")
        icon = ":white_check_mark:" if status in ("added", "already_member") else ":x:"
        group_lines.append(f"{icon} {g.get('group')} — {status}")
    groups_text = "\n".join(group_lines) if group_lines else "No groups configured"

    if email_result.get("ok"):
        email_line = f":envelope: Credentials email sent to {email_result.get('recipient')}"
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
                "text": (
                    f":white_check_mark: *Account created*\n"
                    f"*Workspace:* {created_user.get('primaryEmail') or 'unknown'}\n"
                    f"*Recovery email:* {created_user.get('recoveryEmail') or 'none'}"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Groups*\n{groups_text}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": email_line},
        },
    ]
