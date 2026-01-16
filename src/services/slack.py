import json
import config
from db import INSERT_INTERVIEW_ANSWERS_SLACK_MODAL_SQL, INSERT_SLACK_EVENT_SQL, get_applicant_user_id_by_thread_ts, get_thread_ts
from sqlalchemy import Connection
from typing import Any, Dict, List, Optional, Tuple


import logging

from slack_web import post_message_reply

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
    if event_data.get('thread_ts') is None and event_data.get('parent_message'):
        event_data['thread_ts'] = get_thread_ts(conn, event_data['parent_message'])
    
    # Set applicant_user_id if not set and thread_ts exists
    if event_data.get('applicant_user_id') is None and event_data.get('thread_ts'):
        event_data['applicant_user_id'] = get_applicant_user_id_by_thread_ts(conn, event_data['thread_ts'])

    conn.execute(INSERT_SLACK_EVENT_SQL, event_data)


def save_slack_modal_response(conn: Connection, applicant_user_id: str, thread_ts: str, slack_modal_blocks: str):
    insert_data = {
        "applicant_user_id": applicant_user_id,
        "thread_ts": thread_ts,
        "slack_modal_blocks": slack_modal_blocks,
    }
    conn.execute(
        INSERT_INTERVIEW_ANSWERS_SLACK_MODAL_SQL,
        insert_data
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
    q_count = len(questions)
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Questions & Answers:*"},
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
            "text": {"type": "mrkdwn", "text": f"*Applicant:* {first} {last}\n*Email:* {_fmt(pii.get('Email Address'))}"},
        },
        {"type": "divider"},
    ]

    # Each question becomes one section block
    for lbl, val in questions:
        if len(blocks) >= max_blocks:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Click to view more."}
                    ],
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


def applicant_data_to_dict(data: str) -> dict:
    data_json = json.loads(data)
    return_dict = {}
    
    for field in data_json.values():
        label = field["label"]
        value = field["value"]

        # Currently making assumption that preferred first/last always come after.
        # If that is not the case, will need to update this
        if label == "Preferred First Name":
            if value is not None and len(value) != 0:
                label = "First Name"
            else:
                continue
        elif label == "Preferred Last Name":
            if value is not None and len(value) != 0:
                label = "Last Name"
            else:
                continue
        elif label == "Preferred Pronouns":
            if value is not None and len(value) != 0:
                label = "Pronouns"
            else:
                continue

        return_dict[label] = value

    return return_dict


def post_application(cfg: config.Config, application_data) -> None:    
    blocks = construct_application_blocks(applicant_data_to_dict(application_data))
    logger.info("Sending blocks to slack %s", blocks["blocks"])

    response = post_message_reply(
        cfg=cfg,
        channel=cfg.slack_channel_id,
        text=str(blocks),
        blocks=blocks["blocks"],
    )
    
    return response

def add_default_reacts(cfg: config.Config, channel: str, timestamp: str) -> None:
    from slack_web import add_reaction

    default_reactions = ["++1", "--1"]
    for reaction in default_reactions:
        try:
            add_reaction(cfg, channel, timestamp, reaction)
        except Exception as e:
            logger.error("Failed to add reaction %s: %s", reaction, e)
            
def add_default_message(cfg: config.Config, channel: str, timestamp: str) -> None:
    from slack_web import post_message_reply

    default_message = ("If you know or have met this applicant, please leave some feedback.\n"
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
        logger.error("Failed to post default message: %s", e)