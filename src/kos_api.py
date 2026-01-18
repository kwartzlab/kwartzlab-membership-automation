import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


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
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, timeout=self.timeout_seconds, **kwargs)

        if allow_statuses and response.status_code in allow_statuses:
            return response

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.error("KOS API request failed: %s %s -> %s", method.upper(), url, response.status_code)
            raise exc

        return response
