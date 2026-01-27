import base64
from email import message_from_bytes

import services.mailer as mailer
from templates import email_templates


def _parse_raw_message(raw: str):
    msg = message_from_bytes(base64.urlsafe_b64decode(raw.encode("utf-8")))
    payloads = msg.get_payload()
    if isinstance(payloads, list):
        parts = []
        for part in payloads:
            parts.append(part.get_payload(decode=True).decode("utf-8"))
        body = "\n".join(parts)
    else:
        body = msg.get_payload(decode=True).decode("utf-8")
    return msg, body


def test_acceptance_email_signature(sample_user):
    message = mailer.build_acceptance_email(sample_user)
    msg, body = _parse_raw_message(message["raw"])
    assert msg["subject"] == email_templates.ACCEPTENCE_EMAIL.subject
    assert "Membership Team" in body
    assert "Kwartzlab" in body


def test_return_visit_email_signature(sample_user):
    message = mailer.build_return_visit_email(sample_user)
    msg, body = _parse_raw_message(message["raw"])
    assert msg["subject"] == email_templates.RETURN_EMAIL.subject
    assert "Membership Team" in body
    assert "Kwartzlab" in body


def test_rejection_email_signature(sample_user):
    message = mailer.build_rejection_email(sample_user)
    msg, body = _parse_raw_message(message["raw"])
    assert msg["subject"] == email_templates.REJECTION_EMAIL.subject
    assert "Membership Team" in body
    assert "Kwartzlab" in body
