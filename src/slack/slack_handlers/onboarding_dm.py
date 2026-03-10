import asyncio
import json
import logging
import re
from typing import Any

from services.google_admin import get_admin_directory_service
from services.workspace_onboarding import (
    build_onboarding_preview,
    collect_missing_workspace_users,
    create_workspace_account_for_user,
)

logger = logging.getLogger(__name__)

MAX_MISSING_RESULTS = 15
_ADMIN_SERVICE_CACHE: dict[str, Any] = {}


def _get_admin_service(cfg) -> object:
    service = _ADMIN_SERVICE_CACHE.get("service")
    if service is None:
        service = get_admin_directory_service(
            credentials_file=cfg.credentials_file,
            token_file=cfg.google_admin_token_file,
        )
        _ADMIN_SERVICE_CACHE["service"] = service
    return service


def onboarding_help_text() -> str:
    return (
        "Onboarding DM commands:\n"
        "- `onboard missing` or `onboard list`: show active/hiatus users missing Workspace accounts\n"
        "- `onboard <kos_user_id>`: preview and confirm Workspace account creation for one user\n"
        "- `help`: show this message"
    )


async def handle_onboarding_dm_command(text: str, *, user_id: str, say, cfg, runtime) -> bool:
    lowered = text.lower().strip()

    if lowered in {"onboard missing", "onboard list"}:
        await say("Running onboarding pre-check for users missing Workspace accounts...")
        rows = await asyncio.to_thread(
            collect_missing_workspace_users,
            runtime.kos_api_client,
            _get_admin_service(cfg),
            workspace_domain=cfg.google_workspace_domain,
        )
        await say(blocks=_build_missing_accounts_blocks(rows), text=_missing_accounts_summary_text(rows))
        return True

    match = re.fullmatch(r"onboard\s+(\d+)", lowered)
    if match:
        kos_user_id = int(match.group(1))
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
        actor_user_id = str(body.get("user", {}).get("id") or "")
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

        await respond(
            replace_original=False,
            text=preview["message"],
            blocks=_build_preview_blocks(preview, actor_user_id),
        )

    @app.action("dm_onboard_create")
    async def handle_dm_onboard_create(ack, body, respond):
        await ack()
        actor_user_id = str(body.get("user", {}).get("id") or "")
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
            _get_admin_service(cfg),
            kos_user_id,
            workspace_domain=cfg.google_workspace_domain,
            workspace_groups=list(cfg.google_workspace_groups or []),
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
    summary = {
        "kos_user_id": preview.get("kos_user_id"),
        "kos_name": preview.get("kos_name"),
        "kos_email": preview.get("kos_email"),
        "workspace_primary_email": preview.get("workspace_primary_email"),
        "workspace_recovery_email": preview.get("workspace_recovery_email"),
        "workspace_groups": preview.get("workspace_groups"),
    }
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Onboarding preview*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{json.dumps(summary, indent=2, ensure_ascii=True)}```"},
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
                }
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
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":white_check_mark: {result.get('message', 'Account created.')}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{json.dumps(created_user, indent=2, ensure_ascii=True)}```"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Group assignment results*\n```{json.dumps(group_results, indent=2, ensure_ascii=True)}```",
            },
        },
    ]
