from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import config
from typing import Dict, List, Any

def construct_application_blocks(
    label_values: Dict[str, Any],
    *,
    photo_label: str = "Photo",
    photo_base_url: str = "https://kos.kwartzlab.ca/storage/images/users/",
    photo_ext: str = ".jpeg",
) -> Dict[str, List[Dict[str, Any]]]:
    blocks: List[Dict[str, Any]] = []

    # fixed PII order
    pii_labels = [
        "First Name",
        "Last Name",
        "Preferred First Name",
        "Preferred Last Name",
        "Preferred Pronouns",
        "Email Address",
    ]

    # exclude address fields
    exclude_labels = {
        "Phone Number",
        "Street Address",
        "City",
        "Province",
        "Postal Code",
    }

    def fmt(v: Any) -> str:
        return "—" if v is None or v == "" else str(v)

    # ---- photo ----
    photo_id = label_values.get(photo_label)
    if photo_id:
        blocks.append({
            "type": "image",
            "image_url": f"{photo_base_url}{photo_id}{photo_ext}",
            "alt_text": "Applicant photo",
        })

    # ---- header ----
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Kwartzlab Membership Interview",
            "emoji": True,
        },
    })

    # ---- PII ----
    fields = []
    for lbl in pii_labels:
        if lbl in label_values:
            fields.append({
                "type": "mrkdwn",
                "text": f"*{lbl}*\n{fmt(label_values.get(lbl))}",
            })

    if fields:
        blocks.append({"type": "section", "fields": fields})

    blocks.append({"type": "divider"})

    # ---- questions (everything else, in input order) ----
    for lbl, val in label_values.items():
        if lbl in pii_labels or lbl in exclude_labels or lbl == photo_label:
            continue
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{lbl}*\n{fmt(val)}",
            },
        })

    return {"blocks": blocks}


def post_application(cfg: config.Config, applicant_data: dict) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    
    blocks = construct_application_blocks(applicant_data)

    try:
        response = client.chat_postMessage(
            channel=cfg.slack_channel_id,
            text=str(blocks),
            blocks=blocks["blocks"],
        )
    except SlackApiError as e:
        print(e.response["error"])