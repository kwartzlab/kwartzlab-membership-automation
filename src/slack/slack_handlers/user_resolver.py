import asyncio
import re

import services.kos_api as kos_api

_SLACK_MENTION_PATTERN = re.compile(r"^<@([A-Z0-9]+)>$", re.IGNORECASE)


async def resolve_kos_user_id(arg: str, *, runtime) -> tuple[int | None, str | None]:
    """
    Resolve a command argument to a kOS user ID.

    Accepts either a plain integer (kOS user ID) or a Slack mention (<@UXXXXXX>).
    Returns (kos_user_id, None) on success, or (None, error_message) on failure.
    """
    stripped = arg.strip()

    if stripped.isdigit():
        return int(stripped), None

    mention_match = _SLACK_MENTION_PATTERN.match(stripped)
    if mention_match:
        slack_user_id = mention_match.group(1).upper()
        try:
            response = await runtime.slack_app.client.users_info(user=slack_user_id)
            slack_email = ((response.get("user") or {}).get("profile", {}).get("email", "")).strip().lower()
        except Exception:
            return None, f"Could not look up Slack user <@{slack_user_id}>."

        if not slack_email:
            return None, f"Slack user <@{slack_user_id}> has no email in their profile."

        users = await asyncio.to_thread(runtime.kos_api_client.list_users)
        matches = [u for u in users if str(u.get("email") or "").strip().lower() == slack_email]

        if not matches:
            return None, f"No kOS user found matching Slack user <@{slack_user_id}> (email: `{slack_email}`)."
        if len(matches) > 1:
            names = ", ".join(f"{kos_api.get_user_full_name(u, default='unknown')} (#{u.get('id')})" for u in matches)
            return None, f"Multiple kOS users match `{slack_email}`: {names}. Use the kOS user ID directly."

        return int(matches[0]["id"]), None

    return None, f"Invalid user: `{stripped}`. Use a kOS user ID or @mention."
