import services.kos_api as kos_api


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_list_users_handles_paginated_data(monkeypatch):
    client = kos_api.KosApiClient(base_url="http://example.test", token="token")
    payloads = {
        "/api/users": {"data": [{"id": 1}, {"id": 2}], "next_page_url": "http://example.test/api/users?page=2"},
        "http://example.test/api/users?page=2": {"data": [{"id": 3}], "next_page_url": None},
    }

    def fake_request(method, path, **kwargs):
        return _FakeResponse(payloads[path])

    monkeypatch.setattr(client, "_request", fake_request)

    users = client.list_users()
    assert [user["id"] for user in users] == [1, 2, 3]


def test_extract_users_page_supports_list_payload():
    users, next_path = kos_api._extract_users_page([{"id": 1}, {"id": 2}])
    assert [user["id"] for user in users] == [1, 2]
    assert next_path is None
