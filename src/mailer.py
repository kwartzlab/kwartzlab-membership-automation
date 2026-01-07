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
MEMBERSHIP_GROUP_FROM_NAME = "Membership Coordinator"
MEMBERSHIP_GROUP_FROM_EMAIL = "membership@kwartzlab.ca"
MEMBERSHIP_GROUP_REPLY_TO = "membership@kwartzlab.ca"

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


def build_email_with_template(to: str,
                              from_name: str,
                              from_email: str,
                              email_template: email_templates.Email,
                              template_vars,
                              signature: str,
                              reply_to: str = None,
                              signature_name: str = ""):
    
    template_subject = email_template.subject
    email_body = email_template.body.format(**template_vars)
    email_body += signature.format(signature_name=signature_name)
    
    message = build_group_html_message(
        to=to,
        subject=template_subject,
        text_body=email_body,
        html_body=email_body,
        from_name=from_name,
        from_email=from_email,
        reply_to=reply_to
    )

    return message


def build_acceptance_email(user):
    return build_email_with_template(
            to=user["email"],
            from_name=MEMBERSHIP_GROUP_FROM_NAME,
            from_email=MEMBERSHIP_GROUP_FROM_EMAIL,
            email_template=email_templates.ACCEPTENCE_EMAIL,
            template_vars={
                "name": user["first_preferred"]
            },
            signature=email_templates.MEMBERSHIP_COORDINATOR_SIGNATURE,
        )

def build_return_visit_email(user):
    return build_email_with_template(
            to=user["email"],
            from_name=MEMBERSHIP_GROUP_FROM_NAME,
            from_email=MEMBERSHIP_GROUP_FROM_EMAIL,
            email_template=email_templates.RETURN_EMAIL,
            template_vars={
                "name": user["first_preferred"]
            },
            signature=email_templates.MEMBERSHIP_COORDINATOR_SIGNATURE,
        )

# Main only to test. This should not be run.
if __name__ == "__main__":
    
    test_email_recevier = "saatvik.bhayana@kwartzlab.ca"
    
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(f"Missing {CREDENTIALS_FILE}")

    service = get_gmail_service()

    email_template = email_templates.RETURN_EMAIL

    welcome_email = email_template.body.format(name="FakeName")
    signature = email_templates.MEMBERSHIP_COORDINATOR_SIGNATURE.format(signature_name="Test Membership Coordinator")
    
    message = build_group_html_message(
        to=test_email_recevier,
        subject=email_template.subject,
        text_body=welcome_email + signature,
        html_body=welcome_email + signature,
        from_name=MEMBERSHIP_GROUP_FROM_NAME,
        from_email=MEMBERSHIP_GROUP_FROM_EMAIL,
        reply_to=MEMBERSHIP_GROUP_REPLY_TO,
    )

    response = send_message(service, SENDER_USER_ID, message)
    print("Message sent, id:", response.get("id"))
