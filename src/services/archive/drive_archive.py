import logging
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.send",
]
DRIVE_API_SERVICE = "drive"
DRIVE_API_VERSION = "v3"


def _resolve_path(path_value: str) -> Path:
    return Path(path_value).expanduser().resolve()


def _get_drive_credentials(credentials_file: str, token_file: str) -> Credentials:
    creds = None
    credentials_path = _resolve_path(credentials_file)
    token_path = _resolve_path(token_file)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), DRIVE_SCOPES)

    if not creds or not creds.valid or not creds.has_scopes(DRIVE_SCOPES):
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                DRIVE_SCOPES,
            )
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json())

    return creds


def get_drive_service(credentials_file: str, token_file: str) -> object:
    creds = _get_drive_credentials(credentials_file, token_file)
    return build(DRIVE_API_SERVICE, DRIVE_API_VERSION, credentials=creds, cache_discovery=False)


def parse_drive_folder_id(folder_url: str) -> str | None:
    if not folder_url:
        return None
    folder_url = folder_url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", folder_url):
        return folder_url
    for pattern in (
        r"/folders/([A-Za-z0-9_-]+)",
        r"[?&]id=([A-Za-z0-9_-]+)",
    ):
        match = re.search(pattern, folder_url)
        if match:
            return match.group(1)
    return None


def _find_existing_file(service, *, name: str, folder_id: str) -> str | None:
    escaped = name.replace("'", "\\'")
    response = (
        service.files()
        .list(
            q=f"name='{escaped}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = response.get("files", [])
    return files[0]["id"] if files else None


def upload_file_to_drive(
    file_path: str | Path,
    folder_url: str,
    *,
    credentials_file: str,
    token_file: str,
) -> str | None:
    folder_id = parse_drive_folder_id(folder_url)
    if not folder_id:
        logger.warning("Invalid ARCHIVE_GDRIVE_URL: %s", folder_url)
        return None

    file_path = Path(file_path)
    service = get_drive_service(credentials_file, token_file)
    media = MediaFileUpload(str(file_path), mimetype="text/csv")

    existing_id = _find_existing_file(service, name=file_path.name, folder_id=folder_id)
    if existing_id:
        result = (
            service.files()
            .update(
                fileId=existing_id,
                body={"name": file_path.name},
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    else:
        result = (
            service.files()
            .create(
                body={"name": file_path.name, "parents": [folder_id]},
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    return result.get("webViewLink")
