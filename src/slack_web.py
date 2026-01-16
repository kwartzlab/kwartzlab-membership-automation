import json
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import config
from typing import Dict, List, Any

import logging

logger = logging.getLogger(__name__)
    
def get_users(cfg: config.Config):
    client = WebClient(
        token=cfg.slack_bot_token
    )
    users_info = client.users_list()
    return users_info


def post_message_reply(cfg: config.Config, channel: str, thread_ts: str = None, text: str = "", blocks: list = None, reply_broadcast: bool = False) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    try:
        response = client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=blocks,
            thread_ts=thread_ts,
            reply_broadcast=reply_broadcast,
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


def send_ephemeral_message(cfg: config.Config, channel: str, user: str, text: str = "", blocks: list = None, thread_ts: str = None) -> None:
    client = WebClient(
        token=cfg.slack_bot_token
    )
    try:
        response = client.chat_postEphemeral(
            channel=channel,
            user=user,
            text=text,
            thread_ts=thread_ts,
            blocks=blocks
        )
        logger.info("Ephemeral message sent: %s", response)
        return response
    except SlackApiError as e:
        logger.error(e.response["error"])
        raise e