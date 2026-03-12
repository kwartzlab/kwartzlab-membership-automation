import re
import secrets
import string
import unicodedata
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import services.kos_api as kos_api

ADMIN_DIRECTORY_API_SERVICE = "admin"
ADMIN_DIRECTORY_API_VERSION = "directory_v1"

ADMIN_DIRECTORY_USER_SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group.member",
]

_NAME_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def get_admin_directory_service(credentials_file: str, token_file: str) -> object:
    creds = None

    credentials_path = Path(credentials_file)
    token_path = Path(token_file)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), ADMIN_DIRECTORY_USER_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                ADMIN_DIRECTORY_USER_SCOPES,
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build(
        ADMIN_DIRECTORY_API_SERVICE,
        ADMIN_DIRECTORY_API_VERSION,
        credentials=creds,
        cache_discovery=False,
    )


def _normalize_name_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    allowed = []
    for char in normalized:
        if char.isalnum():
            allowed.append(char)
    return "".join(allowed)


def _normalize_name_component_hyphenated(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    allowed = []
    previous_hyphen = False
    for char in normalized:
        if char.isalnum():
            allowed.append(char)
            previous_hyphen = False
        elif char == "-" and not previous_hyphen and allowed:
            allowed.append(char)
            previous_hyphen = True
    if allowed and allowed[-1] == "-":
        allowed.pop()
    return "".join(allowed)


def _normalize_domain(domain: str) -> str:
    clean_domain = domain.strip().lstrip("@").lower()
    if "." not in clean_domain:
        clean_domain = f"{clean_domain}.ca"
    return clean_domain


def _name_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    return _NAME_TOKEN_PATTERN.findall(normalized)


def _display_name(first_name: str, last_name: str) -> str:
    combined = f"{first_name.strip()} {last_name.strip()}".strip()
    return combined if combined else "New User"


def generate_workspace_primary_email(kos_user: dict[str, Any], domain: str) -> str:
    return generate_workspace_primary_email_candidates(kos_user, domain)[0]


def generate_workspace_primary_email_candidates(kos_user: dict[str, Any], domain: str) -> list[str]:
    first_name = _normalize_name_component(kos_api.get_user_first_name(kos_user))
    last_name = _normalize_name_component(kos_api.get_user_last_name(kos_user))
    last_name_hyphenated = _normalize_name_component_hyphenated(kos_api.get_user_last_name(kos_user))

    if not first_name or not last_name:
        raise ValueError("kOS user is missing first or last name required for Workspace email generation.")

    clean_domain = _normalize_domain(domain)
    candidates = [
        f"{first_name}.{last_name}@{clean_domain}",
        f"{first_name}{last_name}@{clean_domain}",
    ]
    if last_name_hyphenated and last_name_hyphenated != last_name:
        candidates.append(f"{first_name}.{last_name_hyphenated}@{clean_domain}")

    raw_first = kos_api.get_user_first_name(kos_user)
    raw_last = kos_api.get_user_last_name(kos_user)
    first_tokens = _name_tokens(raw_first)
    last_tokens = _name_tokens(raw_last)
    if first_tokens and last_tokens:
        dotted = f"{'.'.join(first_tokens)}.{'.'.join(last_tokens)}@{clean_domain}"
        candidates.append(dotted)

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)
    return unique_candidates


def generate_initial_password(length: int = 20) -> str:
    if length < 12:
        raise ValueError("Initial password length must be at least 12 characters.")
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_workspace_user_insert_body(
    kos_user: dict[str, Any],
    *,
    domain: str,
    initial_password: str | None = None,
    change_password_at_next_login: bool = True,
) -> dict[str, Any]:
    first_name = kos_api.get_user_first_name(kos_user).strip()
    last_name = kos_api.get_user_last_name(kos_user).strip()
    if not first_name or not last_name:
        raise ValueError("kOS user is missing first or last name.")

    primary_email = generate_workspace_primary_email(kos_user, domain)
    password = initial_password or generate_initial_password()

    body: dict[str, Any] = {
        "name": {
            "givenName": first_name,
            "familyName": last_name,
            "fullName": _display_name(first_name, last_name),
        },
        "primaryEmail": primary_email,
        "password": password,
        "changePasswordAtNextLogin": change_password_at_next_login,
    }

    kos_email = kos_user.get("email")
    if kos_email:
        body["recoveryEmail"] = str(kos_email)

    return body


def create_workspace_user(
    admin_directory_service: object,
    *,
    user_insert_body: dict[str, Any],
) -> dict[str, Any]:
    return admin_directory_service.users().insert(body=user_insert_body).execute()


def reset_workspace_user_password(
    admin_directory_service: object,
    *,
    user_email: str,
    new_password: str,
    change_password_at_next_login: bool = True,
) -> dict[str, Any]:
    body = {
        "password": new_password,
        "changePasswordAtNextLogin": change_password_at_next_login,
    }
    return admin_directory_service.users().update(userKey=user_email, body=body).execute()


def add_user_to_group(
    admin_directory_service: object,
    *,
    group_key: str,
    user_email: str,
    role: str = "MEMBER",
) -> dict[str, Any]:
    body = {
        "email": user_email,
        "role": role,
    }
    return admin_directory_service.members().insert(groupKey=group_key, body=body).execute()


def list_workspace_user_emails(
    admin_directory_service: object,
    *,
    domain: str | None = None,
    customer: str = "my_customer",
    max_results: int = 500,
) -> set[str]:
    user_emails: set[str] = set()
    page_token: str | None = None
    clean_domain = _normalize_domain(domain) if domain else None

    while True:
        response = (
            admin_directory_service.users()
            .list(
                customer=customer,
                maxResults=max_results,
                orderBy="email",
                pageToken=page_token,
            )
            .execute()
        )
        users = response.get("users", [])
        for user in users:
            email = str(user.get("primaryEmail") or "").strip().lower()
            if not email:
                continue
            if clean_domain and not email.endswith(f"@{clean_domain}"):
                continue
            user_emails.add(email)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return user_emails


def list_group_member_emails(
    admin_directory_service: object,
    *,
    group_key: str,
    max_results: int = 200,
    include_derived_membership: bool = True,
) -> set[str]:
    member_emails: set[str] = set()
    page_token: str | None = None

    while True:
        response = (
            admin_directory_service.members()
            .list(
                groupKey=group_key,
                maxResults=max_results,
                pageToken=page_token,
                includeDerivedMembership=include_derived_membership,
            )
            .execute()
        )
        members = response.get("members", [])
        for member in members:
            email = str(member.get("email") or "").strip().lower()
            if email:
                member_emails.add(email)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return member_emails


def list_workspace_recovery_email_index(
    admin_directory_service: object,
    *,
    domain: str | None = None,
    customer: str = "my_customer",
    max_results: int = 500,
) -> dict[str, set[str]]:
    recovery_to_primary: dict[str, set[str]] = {}
    page_token: str | None = None
    clean_domain = _normalize_domain(domain) if domain else None

    while True:
        response = (
            admin_directory_service.users()
            .list(
                customer=customer,
                maxResults=max_results,
                orderBy="email",
                pageToken=page_token,
            )
            .execute()
        )
        users = response.get("users", [])
        for user in users:
            primary_email = str(user.get("primaryEmail") or "").strip().lower()
            if not primary_email:
                continue
            if clean_domain and not primary_email.endswith(f"@{clean_domain}"):
                continue

            recovery_email = str(user.get("recoveryEmail") or "").strip().lower()
            if recovery_email:
                recovery_to_primary.setdefault(recovery_email, set()).add(primary_email)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return recovery_to_primary


def get_workspace_user_by_email(admin_directory_service: object, *, user_email: str) -> dict | None:
    try:
        return admin_directory_service.users().get(userKey=user_email).execute()
    except HttpError as exc:
        if getattr(getattr(exc, "resp", None), "status", None) == 404:
            return None
        raise


def is_user_in_group(admin_directory_service: object, *, group_key: str, user_email: str) -> bool:
    try:
        admin_directory_service.members().get(groupKey=group_key, memberKey=user_email).execute()
        return True
    except HttpError as exc:
        if getattr(getattr(exc, "resp", None), "status", None) == 404:
            return False
        raise


def has_member_in_group(admin_directory_service: object, *, group_key: str, user_email: str) -> bool:
    try:
        response = admin_directory_service.members().hasMember(groupKey=group_key, memberKey=user_email).execute()
    except HttpError as exc:
        if getattr(getattr(exc, "resp", None), "status", None) == 404:
            return False
        raise
    return bool(response.get("isMember"))
