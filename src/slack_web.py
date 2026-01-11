import json
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import config
from typing import Dict, List, Any

import logging

logger = logging.getLogger(__name__)

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
        # "Preferred First Name",
        # "Preferred Last Name",
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
            "image_url": f"https://i.imgur.com/733Q0Rq.jpeg",
            # "image_url": f"{photo_base_url}{photo_id}{photo_ext}",
            "alt_text": "Applicant photo",
        })

    # ---- header ----
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{label_values.get('First Name', 'Unknown')} {label_values.get('Last Name', 'Unknown')} - Kwartzlab Membership Interview",
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
        if value is None or len(value) == 0:
            value = "--"

        return_dict[label] = value

    return return_dict



def post_application(cfg: config.Config, application_data) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    
    blocks = construct_application_blocks(applicant_data_to_dict(application_data))
    logger.info("Sending blocks to slack %s", blocks["blocks"])

    try:
        response = client.chat_postMessage(
            channel=cfg.slack_channel_id,
            text=str(blocks),
            blocks=blocks["blocks"],
        )
        logger.info("Response received: %s", response)
        return response
    except SlackApiError as e:
        logger.error(e.response["error"])
        raise e
    
def get_users(cfg: config.Config):
    client = WebClient(
        token=cfg.slack_bot_token
    )
    users_info = client.users_list()
    return users_info


def post_message_reply(cfg: config.Config, channel: str, thread_ts: str, message: str) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    try:
        response = client.chat_postMessage(
            channel=channel,
            text=message,
            thread_ts=thread_ts,
        )
        logger.info("Reply posted: %s", response)
        return response
    except SlackApiError as e:
        logger.error(e.response["error"])
        raise e
    
    
def add_reaction(cfg: config.Config, channel: str, timestamp: str, reaction: str) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    try:
        response = client.reactions_add(
            channel=channel,
            timestamp=timestamp,
            name=reaction,
        )
        logger.info("Reaction added: %s", response)
        return response
    except SlackApiError as e:
        logger.error(e.response["error"])
        raise e
    
    
def remove_reaction(cfg: config.Config, channel: str, timestamp: str, reaction: str) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    try:
        response = client.reactions_remove(
            channel=channel,
            timestamp=timestamp,
            name=reaction,
        )
        logger.info("Reaction removed: %s", response)
        return response
    except SlackApiError as e:
        logger.error(e.response["error"])
        raise e

def get_user_group(cfg: config.Config, usergroup_id: str):
    client = WebClient(
        token=cfg.slack_bot_token
    )
    try:
        response = client.usergroups_users_list(
            usergroup=usergroup_id
        )
        logger.info("User group members fetched: %s", response)
        return response
    except SlackApiError as e:
        logger.error(e.response["error"])
        raise e


def send_ephemeral_message(cfg: config.Config, channel: str, user: str, message: str, thread_ts: str = None) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    try:
        response = client.chat_postEphemeral(
            channel=channel,
            user=user,
            text=message,
            thread_ts=thread_ts,
        )
        logger.info("Ephemeral message sent: %s", response)
        return response
    except SlackApiError as e:
        logger.error(e.response["error"])
        raise e