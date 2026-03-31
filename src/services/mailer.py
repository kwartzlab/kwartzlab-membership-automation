import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import services.kos_api as kos_api
from templates import email_templates

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
]

GMAIL_API_SERVICE = "gmail"
GMAIL_API_VERSION = "v1"

SENDER_USER_ID = "me"

# Group / alias configuration
MEMBERSHIP_GROUP_FROM_NAME = "Membership Coordinator"
MEMBERSHIP_GROUP_FROM_EMAIL = "membership@kwartzlab.ca"
MEMBERSHIP_GROUP_REPLY_TO = "membership@kwartzlab.ca"
DEFAULT_SIGNATURE_ROLE = "Membership Team"


def get_gmail_service(credentials_file: str, token_file: str) -> object:
    creds = None

    credentials_file = Path(credentials_file)
    token_file = Path(token_file)

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
    bcc: str | None = None,
    reply_to: str | None = None,
) -> dict:
    msg = MIMEMultipart("alternative")
    msg["to"] = to
    msg["subject"] = subject
    msg["from"] = f"{from_name} <{from_email}>" if from_name else from_email
    if bcc:
        msg["bcc"] = bcc

    if reply_to:
        msg["reply-to"] = reply_to

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_message(service, user_id: str, message: dict):
    return service.users().messages().send(userId=user_id, body=message).execute()


def build_email_with_template(
    to: str,
    from_name: str,
    from_email: str,
    email_template: email_templates.Email,
    template_vars,
    signature: str,
    bcc: str | None = None,
    reply_to: str = None,
    signature_name: str = "",
    signature_role: str | None = None,
):
    template_subject = email_template.subject
    email_body = email_template.body.format(**template_vars)
    if signature_role is None:
        signature_role = DEFAULT_SIGNATURE_ROLE
    signature_role_block = f"<p><b>{signature_role}</b></p>" if signature_role else ""
    email_body += signature.format(
        signature_name=signature_name,
        signature_role_block=signature_role_block,
    )

    message = build_group_html_message(
        to=to,
        subject=template_subject,
        text_body=email_body,
        html_body=email_body,
        from_name=from_name,
        from_email=from_email,
        bcc=bcc,
        reply_to=reply_to,
    )

    return message


def _resolve_bcc_and_signature(
    *,
    bcc_self: bool,
    signature_name: str | None,
    signature_role: str | None,
) -> tuple[str | None, str]:
    bcc = MEMBERSHIP_GROUP_FROM_EMAIL if bcc_self else None
    signature = email_templates.MEMBERSHIP_TEAM_SIGNATURE
    if signature_name or signature_role:
        signature = email_templates.CUSTOM_SIGNATURE
    return bcc, signature


def _build_membership_email(
    user,
    *,
    email_template: email_templates.Email,
    from_name: str | None = None,
    signature_name: str | None = None,
    signature_role: str | None = None,
    bcc_self: bool = True,
    reply_to: str | None = None,
):
    bcc, signature = _resolve_bcc_and_signature(
        bcc_self=bcc_self,
        signature_name=signature_name,
        signature_role=signature_role,
    )
    return build_email_with_template(
        to=user["email"],
        from_name=from_name or MEMBERSHIP_GROUP_FROM_NAME,
        from_email=MEMBERSHIP_GROUP_FROM_EMAIL,
        email_template=email_template,
        template_vars={"name": kos_api.get_user_first_name(user, default="there")},
        signature=signature,
        bcc=bcc,
        signature_name=signature_name or "",
        signature_role=signature_role,
        reply_to=reply_to or MEMBERSHIP_GROUP_REPLY_TO,
    )


def build_acceptance_email(
    user,
    *,
    from_name: str | None = None,
    signature_name: str | None = None,
    signature_role: str | None = None,
    bcc_self: bool = True,
    reply_to: str | None = None,
):
    return _build_membership_email(
        user,
        email_template=email_templates.ACCEPTANCE_EMAIL,
        from_name=from_name,
        signature_name=signature_name,
        signature_role=signature_role,
        bcc_self=bcc_self,
        reply_to=reply_to,
    )


def build_return_visit_email(
    user,
    *,
    from_name: str | None = None,
    signature_name: str | None = None,
    signature_role: str | None = None,
    bcc_self: bool = True,
    reply_to: str | None = None,
):
    return _build_membership_email(
        user,
        email_template=email_templates.RETURN_EMAIL,
        from_name=from_name,
        signature_name=signature_name,
        signature_role=signature_role,
        bcc_self=bcc_self,
        reply_to=reply_to,
    )


def build_rejection_email(
    user,
    *,
    from_name: str | None = None,
    signature_name: str | None = None,
    signature_role: str | None = None,
    bcc_self: bool = True,
    reply_to: str | None = None,
):
    return _build_membership_email(
        user,
        email_template=email_templates.REJECTION_EMAIL,
        from_name=from_name,
        signature_name=signature_name,
        signature_role=signature_role,
        bcc_self=bcc_self,
        reply_to=reply_to,
    )


def _build_workspace_email(
    user: dict,
    *,
    workspace_email: str,
    initial_password: str,
    tmpl: email_templates.Email,
) -> tuple[str, str]:
    html_vars = {
        "first_name": escape(kos_api.get_user_first_name(user, default="there")),
        "full_name": escape(kos_api.get_user_full_name(user, default="there")),
        "workspace_email": escape(workspace_email),
        "initial_password": escape(initial_password),
    }
    return tmpl.subject, tmpl.body.format(**html_vars)


def _send_workspace_email(
    user: dict,
    *,
    workspace_email: str,
    initial_password: str,
    gmail_service,
    tmpl: email_templates.Email,
    log_label: str,
) -> dict:
    if gmail_service is None:
        return {"ok": False, "reason": "no_gmail_service"}

    recipient = str(user.get("email") or "").strip()
    if not recipient:
        return {"ok": False, "reason": "no_kos_email"}

    subject, body = _build_workspace_email(
        user, workspace_email=workspace_email, initial_password=initial_password, tmpl=tmpl
    )
    try:
        message = build_group_html_message(
            to=recipient,
            subject=subject,
            text_body=body,
            html_body=body,
            from_name=MEMBERSHIP_GROUP_FROM_NAME,
            from_email=MEMBERSHIP_GROUP_FROM_EMAIL,
            reply_to=MEMBERSHIP_GROUP_REPLY_TO,
            bcc=MEMBERSHIP_GROUP_FROM_EMAIL,
        )
        send_message(service=gmail_service, user_id=SENDER_USER_ID, message=message)
        return {"ok": True, "recipient": recipient}
    except Exception as exc:
        logger.exception("Failed to send %s to %s.", log_label, recipient)
        return {"ok": False, "reason": str(exc)}


def send_workspace_credentials_email(
    user: dict,
    *,
    workspace_email: str,
    initial_password: str,
    gmail_service,
) -> dict:
    return _send_workspace_email(
        user,
        workspace_email=workspace_email,
        initial_password=initial_password,
        gmail_service=gmail_service,
        tmpl=email_templates.WORKSPACE_CREDENTIALS_EMAIL,
        log_label="workspace credentials email",
    )


def send_workspace_password_reset_email(
    user: dict,
    *,
    workspace_email: str,
    new_password: str,
    gmail_service,
) -> dict:
    return _send_workspace_email(
        user,
        workspace_email=workspace_email,
        initial_password=new_password,
        gmail_service=gmail_service,
        tmpl=email_templates.WORKSPACE_PASSWORD_RESET_EMAIL,
        log_label="workspace password reset email",
    )
