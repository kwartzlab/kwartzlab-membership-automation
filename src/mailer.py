import base64
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import email_templates

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"

GMAIL_API_SERVICE = "gmail"
GMAIL_API_VERSION = "v1"

SENDER_USER_ID = "me"

# Group / alias configuration
GROUP_FROM_NAME = "Membership Coordinator"
GROUP_FROM_EMAIL = "membership@kwartzlab.ca"
GROUP_REPLY_TO = "membership@kwartzlab.ca"

def get_gmail_service():
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())

    return build(GMAIL_API_SERVICE, GMAIL_API_VERSION, credentials=creds, cache_discovery=False)

def build_group_html_message(
    to: str,
    subject: str,
    text_body: str,
    html_body: str,
    from_name: str,
    from_email: str,
    reply_to: str | None = None,
) -> dict:
    msg = MIMEMultipart("alternative")
    msg["to"] = to
    msg["subject"] = subject
    msg["from"] = f"{from_name} <{from_email}>" if from_name else from_email

    if reply_to:
        msg["reply-to"] = reply_to

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}

def send_message(service, user_id: str, message: dict):
    return (
        service.users()
        .messages()
        .send(userId=user_id, body=message)
        .execute()
    )



if __name__ == "__main__":
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(f"Missing {CREDENTIALS_FILE}")

    service = get_gmail_service()

    email_tempalte = email_templates.RETURN_EMAIL

    welcome_email = email_tempalte.body.format(name="Saatvik")
    signature = email_templates.SIGNATURE.format(membership_coordinator_name="Saatvik Bhayana")
    
    message = build_group_html_message(
        to="saatvik.bhayana@kwartzlab.ca",
        subject=email_tempalte.subject,
        text_body=welcome_email + signature,
        html_body=welcome_email + signature,
        from_name=GROUP_FROM_NAME,
        from_email=GROUP_FROM_EMAIL,
        reply_to=GROUP_REPLY_TO,
    )

    response = send_message(service, SENDER_USER_ID, message)
    print("Message sent, id:", response.get("id"))
