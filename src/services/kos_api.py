import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


_FIRST_NAME_KEYS = (
    "first_preferred",
    "preferred_first_name",
    "first_name",
    "first",
)
_LAST_NAME_KEYS = (
    "last_preferred",
    "preferred_last_name",
    "last_name",
    "last",
)


def get_user_field(user: dict | None, keys: tuple[str, ...], default: str = "") -> str:
    if not user:
        return default
    for key in keys:
        value = user.get(key)
        if value:
            value = str(value).strip()
            if value:
                return value
    return default


def get_user_first_name(user: dict | None, default: str = "") -> str:
    return get_user_field(user, _FIRST_NAME_KEYS, default=default)


def get_user_last_name(user: dict | None, default: str = "") -> str:
    return get_user_field(user, _LAST_NAME_KEYS, default=default)


def get_user_full_name(user: dict | None, default: str = "Applicant") -> str:
    first = get_user_first_name(user)
    last = get_user_last_name(user)
    if first and last:
        return f"{first} {last}"
    return first or last or default


ACTIVE_STATUSES: frozenset[str] = frozenset({"active", "hiatus"})


def is_active_or_hiatus(user: dict) -> bool:
    return str(user.get("status") or "").strip().lower() in ACTIVE_STATUSES


class KosApiClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
            }
        )

    def get_user(self, user_id: int) -> Optional[dict]:
        return self._get_json(f"/api/users/{user_id}")

    def list_users(self) -> list[dict]:
        users: list[dict] = []
        next_path: Optional[str] = "/api/users"
        while next_path:
            payload = self._request_json("get", next_path)
            page_users, next_path = _extract_users_page(payload)
            users.extend(page_users)
        return users

    def get_next_user_status(self, status_id: int) -> Optional[dict]:
        response = self._request("get", f"/api/user_statuses?status_id={status_id}", allow_statuses={204})
        if response.status_code == 204:
            return None
        return response.json()

    def get_upcoming_user_statuses(self, days: int = 7) -> list[dict]:
        payload = self._request_json("get", f"/api/user_statuses/upcoming?days={days}")
        if isinstance(payload, list):
            return payload
        return payload.get("data", [])

    def get_latest_user_status_id(self) -> int:
        """Return the id of the most recent user status record, or 0 if none exist."""
        payload = self._get_json("/api/user_statuses/latest")
        return int(payload.get("id", 0)) if payload else 0

    def get_next_outbox(self) -> Optional[dict]:
        response = self._request("get", "/api/form_submissions/outbox/next", allow_statuses={404})
        if response.status_code in (204, 404):
            if response.status_code == 404:
                logger.debug("No outbox items available (kOS returned 404).")
            return None
        return response.json()

    def get_outbox(self, outbox_id: int) -> Optional[dict]:
        try:
            return self._get_json(f"/api/form_submissions/outbox/{outbox_id}")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (404, 405):
                return None
            raise

    def get_form_submission(self, form_submission_id: int) -> Optional[dict]:
        try:
            return self._get_json(f"/api/form_submissions/{form_submission_id}")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    def mark_outbox(self, outbox_id: int, last_error: Optional[str] = None) -> dict:
        payload: Optional[dict[str, Any]]
        if last_error is None:
            payload = None
        else:
            payload = {"last_error": last_error}

        try:
            return self._request_json("post", f"/api/form_submissions/outbox/{outbox_id}", json=payload)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                return exc.response.json()
            raise

    def _get_json(self, path: str) -> Optional[dict]:
        try:
            response = self._request("get", path)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

        return response.json()

    def _request_json(self, method: str, path: str, **kwargs) -> dict:
        response = self._request(method, path, **kwargs)
        return response.json()

    def _request(
        self, method: str, path: str, *, allow_statuses: Optional[set[int]] = None, **kwargs
    ) -> requests.Response:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{self.base_url}{path}"
        response = self.session.request(method, url, timeout=self.timeout_seconds, **kwargs)

        if allow_statuses and response.status_code in allow_statuses:
            return response

        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.error("KOS API request failed: %s %s -> %s", method.upper(), url, response.status_code)
            raise

        return response


def _extract_users_page(payload: Any) -> tuple[list[dict], Optional[str]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], None

    if not isinstance(payload, dict):
        raise ValueError("Unexpected users payload type from kOS API.")

    if isinstance(payload.get("data"), list):
        users = [item for item in payload["data"] if isinstance(item, dict)]
        next_path = payload.get("next_page_url")
        return users, str(next_path) if next_path else None

    if isinstance(payload.get("users"), list):
        users = [item for item in payload["users"] if isinstance(item, dict)]
        next_path = payload.get("next_page_url")
        return users, str(next_path) if next_path else None

    if isinstance(payload.get("results"), list):
        users = [item for item in payload["results"] if isinstance(item, dict)]
        next_path = payload.get("next_page_url")
        return users, str(next_path) if next_path else None

    raise ValueError("Could not locate user list in kOS API response.")


def mark_outbox_on_error(
    kos_api_client: KosApiClient,
    outbox_id: int,
    exc: Exception,
    *,
    log: logging.Logger | None = None,
    max_error_len: int = 1000,
) -> None:
    """Log and mark an outbox item with a truncated error message."""
    (log or logger).exception("Failed to process outbox_id %s.", outbox_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    error_text = str(exc)[: (max_error_len - len(timestamp) - 50)]  # leave room for timestamp and extra info
    payload = {
        "timestamp": timestamp,
        "error": error_text,
    }
    kos_api_client.mark_outbox(outbox_id, last_error=json.dumps(payload, ensure_ascii=True))
