import base64
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from templates import email_templates

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

GMAIL_API_SERVICE = "gmail"
GMAIL_API_VERSION = "v1"

SENDER_USER_ID = "me"

# Group / alias configuration
MEMBERSHIP_GROUP_FROM_NAME = "Membership Coordinator"
MEMBERSHIP_GROUP_FROM_EMAIL = "membership@kwartzlab.ca"
MEMBERSHIP_GROUP_REPLY_TO = "membership@kwartzlab.ca"

def get_gmail_service(credentials_file: str, token_file: str) -> object:
    
    creds = None
    base_path = Path(__file__).resolve().parents[1]
    credentials_file = Path(base_path, credentials_file)
    token_file = Path(base_path, token_file)
    
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        token_file.write_text(creds.to_json())

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

def build_rejection_email(user):
    return build_email_with_template(
            to=user["email"],
            from_name=MEMBERSHIP_GROUP_FROM_NAME,
            from_email=MEMBERSHIP_GROUP_FROM_EMAIL,
            email_template=email_templates.REJECTION_EMAIL,
            template_vars={
                "name": user["first_preferred"]
            },
            signature=email_templates.MEMBERSHIP_COORDINATOR_SIGNATURE,
        )
