from typing import Any

from services.google_admin import get_admin_directory_service

_ADMIN_SERVICE_CACHE: dict[str, Any] = {}


def get_admin_service(cfg) -> object:
    service = _ADMIN_SERVICE_CACHE.get("service")
    if service is None:
        service = get_admin_directory_service(
            credentials_file=cfg.credentials_file,
            token_file=cfg.google_admin_token_file,
        )
        _ADMIN_SERVICE_CACHE["service"] = service
    return service


def get_actor_user_id(body: dict) -> str:
    """Extract the acting user's Slack ID from a Bolt action body."""
    return str((body.get("user") or {}).get("id") or "")


def is_message_channel_type(channel_type: str, *, invert: bool = False):
    async def matcher(event, **_) -> bool:
        result = event.get("channel_type") == channel_type
        return not result if invert else result

    return matcher
