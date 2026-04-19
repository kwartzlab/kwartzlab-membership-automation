import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Connection

from core import config
from services.db import (
    get_applicant_user_id_by_thread_ts,
    get_thread_ts,
    insert_interview_answers_slack_modal_row,
    insert_slack_event_row,
)
from services.kos_api import get_user_full_name
from services.slack.slack_web import post_message_reply
from utils.forms import applicant_data_to_dict

logger = logging.getLogger(__name__)

PII_LABELS = [
    "First Name",
    "Last Name",
    "Pronouns",
    "Email Address",
]

EXCLUDE_LABELS = {
    "Phone Number",
    "Street Address",
    "City",
    "Province",
    "Postal Code",
}

DEFAULT_PHOTO_LABEL = "Photo"


def insert_slack_event(conn: Connection, event_data: dict):
    # Resolve thread_ts for reactions if needed
    if event_data.get("thread_ts") is None and event_data.get("parent_message"):
        event_data["thread_ts"] = get_thread_ts(conn, event_data["parent_message"])

    # Set applicant_user_id if not set and thread_ts exists
    if event_data.get("applicant_user_id") is None and event_data.get("thread_ts"):
        event_data["applicant_user_id"] = get_applicant_user_id_by_thread_ts(conn, event_data["thread_ts"])

    event_data.setdefault("form_submission_id", None)

    insert_slack_event_row(conn, event_data)


def save_slack_modal_response(
    conn: Connection,
    applicant_user_id: str,
    thread_ts: str,
    form_submission_id: str | None,
    slack_modal_blocks: str,
):
    insert_interview_answers_slack_modal_row(
        conn,
        applicant_user_id=applicant_user_id,
        thread_ts=thread_ts,
        form_submission_id=form_submission_id,
        slack_modal_blocks=slack_modal_blocks,
    )


def _fmt(v: Any) -> str:
    return "—" if v is None or v == "" else str(v)


def split_pii_and_questions(
    label_values: Dict[str, Any],
    *,
    photo_label: str = DEFAULT_PHOTO_LABEL,
) -> Tuple[Dict[str, Any], List[Tuple[str, Any]], Optional[str]]:
    """
    Returns (pii_dict, questions_list_in_order, photo_id)
    questions_list_in_order preserves original iteration order of label_values.
    """
    pii: Dict[str, Any] = {}
    questions: List[Tuple[str, Any]] = []
    photo_id: Optional[str] = None

    for lbl, val in label_values.items():
        if lbl == photo_label:
            photo_id = val
            continue
        if lbl in EXCLUDE_LABELS:
            continue
        if lbl in PII_LABELS:
            pii[lbl] = val
            continue
        questions.append((lbl, val))

    return pii, questions, photo_id


def construct_application_blocks(
    label_values: Dict[str, Any],
    *,
    photo_label: str = DEFAULT_PHOTO_LABEL,
    photo_base_url: str = "https://kos.kwartzlab.ca/storage/images/users/",
    photo_ext: str = ".jpeg",
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Message blocks: show photo + header + PII summary + one button.
    All questions are shown via a modal opened from the button.
    """
    blocks: List[Dict[str, Any]] = []

    pii, questions, photo_id = split_pii_and_questions(label_values, photo_label=photo_label)

    # ---- photo ----
    if photo_id:
        blocks.append(
            {
                "type": "image",
                "image_url": f"{photo_base_url}{photo_id}{photo_ext}",
                "alt_text": "Applicant photo",
            }
        )

    # ---- header ----
    first = label_values.get("First Name", "Unknown")
    last = label_values.get("Last Name", "Unknown")

    blocks.append(
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{first} {last} - Kwartzlab Membership Interview", "emoji": True},
        }
    )

    # ---- PII ----
    fields = []
    for lbl in PII_LABELS:
        if lbl in pii:
            fields.append({"type": "mrkdwn", "text": f"*{lbl}*\n{_fmt(pii.get(lbl))}"})

    if fields:
        blocks.append({"type": "section", "fields": fields})

    blocks.append({"type": "divider"})

    # ---- CTA: open modal with questions ----
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Questions & Answers:*"},
        }
    )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "view_application_questions",  # Slack action handler listens to this
                    "text": {"type": "plain_text", "text": "View Responses", "emoji": True},
                    "style": "primary",
                    "value": "View Responses",
                }
            ],
        }
    )

    return {"blocks": blocks}


def build_questions_modal_view(
    application_data: Dict[str, Any],
    *,
    title: str = "Application Questions",
    photo_label: str = DEFAULT_PHOTO_LABEL,
    max_blocks: int = 95,  # keep some headroom under Slack's 100-block limit
) -> Dict[str, Any]:
    """
    Modal view showing all questions as read-only sections.
    Notes:
      - Slack has strict block & text length limits. This truncates if needed.
      - If you expect many/very long answers, consider pagination or a "View full text" link.
    """
    label_values = applicant_data_to_dict(application_data)
    pii, questions, _photo_id = split_pii_and_questions(label_values, photo_label=photo_label)

    first = label_values.get("First Name", "Unknown")
    last = label_values.get("Last Name", "Unknown")

    blocks: List[Dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Applicant:* {first} {last}\n*Email:* {_fmt(pii.get('Email Address'))}",
            },
        },
        {"type": "divider"},
    ]

    # Each question becomes one section block
    for lbl, val in questions:
        if len(blocks) >= max_blocks:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "Click to view more."}],
                }
            )
            break

        text = f"*{lbl}*\n\n>{_fmt(val)}"
        # Slack mrkdwn per block has limits; keep it safe-ish.
        if len(text) > 2900:
            text = text[:2900] + "…"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": title[:24]},  # Slack title max is 24 chars
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
    }


def post_application(cfg: config.Config, application_data) -> None:
    blocks = construct_application_blocks(applicant_data_to_dict(application_data))
    logger.debug("Sending application blocks to slack channel %s.", cfg.slack_channel_id)

    response = post_message_reply(
        cfg=cfg,
        channel=cfg.slack_channel_id,
        text=str(blocks),
        blocks=blocks["blocks"],
    )

    return response


def post_status_change(
    cfg: config.Config,
    status: dict,
    user: dict | None,
    slack_user_id: str | None,
    updated_by_user: dict | None,
) -> None:
    if slack_user_id:
        subject = f"<@{slack_user_id}>"
    elif user:
        subject = get_user_full_name(user, default=f"user #{status['user_id']}")
    else:
        subject = f"user #{status['user_id']}"

    effective = _fmt_date(status.get("created_at"))
    updater = get_user_full_name(updated_by_user) if updated_by_user else f"user #{status.get('updated_by')}"

    lines = [
        f"*Membership status change*",
        f"{subject} — {status['status']}",
    ]
    if status.get("note"):
        lines.append(f"Note: {status['note']}")
    lines.append(f"Updated by: {updater}")
    lines.append(f"Effective: {effective}")

    post_message_reply(
        cfg=cfg,
        channel=cfg.slack_status_updates_channel_id,
        text="\n".join(lines),
    )


def post_upcoming_statuses_digest(
    cfg: config.Config,
    statuses: list[dict],
    users: dict[int, dict],
    slack_id_by_kos_id: dict[int, str | None],
) -> None:
    if not statuses:
        return

    bullets = []
    for s in statuses:
        uid = s["user_id"]
        slack_id = slack_id_by_kos_id.get(uid)
        if slack_id:
            name = f"<@{slack_id}>"
        else:
            name = get_user_full_name(users.get(uid), default=f"user #{uid}")
        effective = _fmt_date(s.get("created_at"))
        bullets.append(f"• {name} — {s['status']} ({effective})")

    text = "*Upcoming membership status changes (next 7 days)*\n" + "\n".join(bullets)
    post_message_reply(
        cfg=cfg,
        channel=cfg.slack_status_updates_channel_id,
        text=text,
    )


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%b %-d, %Y")
    except (ValueError, AttributeError):
        return iso


def add_default_reacts(cfg: config.Config, channel: str, timestamp: str) -> None:
    from services.slack.slack_web import add_reaction

    default_reactions = ["++1", "--1"]
    for reaction in default_reactions:
        try:
            add_reaction(cfg, channel, timestamp, reaction)
        except Exception as e:
            logger.error("Failed to add reaction %s in channel %s at %s: %s", reaction, channel, timestamp, e)


def add_default_message(cfg: config.Config, channel: str, timestamp: str) -> None:
    from services.slack.slack_web import post_message_reply

    default_message = (
        "If you know or have met this applicant, please leave some feedback.\n"
        "If you endorse their membership, react above with a :++1:.\n"
        "An applicant requires five +1's to become a member.\n\n"
        "If for any reason you believe they should not be accepted, react above with a :--1:.\n"
        "If you're uncomfortable posting your reason in thread,"
        "please contact the membership coordinator directly to discuss."
    )
    try:
        post_message_reply(
            cfg=cfg,
            channel=channel,
            thread_ts=timestamp,
            text=default_message,
        )
    except Exception as e:
        logger.error("Failed to post default message in channel %s at %s: %s", channel, timestamp, e)
