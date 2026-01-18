import json
import logging

import config
import kos_api
from services.slack import (
    add_default_message,
    add_default_reacts,
    build_questions_modal_view,
    insert_slack_event,
    post_application,
    save_slack_modal_response,
)

logger = logging.getLogger(__name__)


def process_one(kos_api_client: kos_api.KosApiClient, slack_conn, cfg: config.Config, outbox_id: int = None):
    application = get_application_from_outbox(kos_api_client, outbox_id=outbox_id)
    if not application:
        return {"No outbox item to process"}
    outbox_id = application["outbox_id"]
    try:
        logger.info(
            "Processing submission %s (outbox_id=%s).",
            application["form_submission_id"],
            outbox_id,
        )
        response = post_application(
            cfg=cfg,
            application_data=application["data"],
        )
        ts = response["ts"]
        event_data = {
            "thread_ts": ts,
            "user_id": "bot",
            "user_name": "bot",
            "event": "post",
            "message": "",
            "parent_message": None,
            "raw_response": json.dumps(response.data),
            "timestamp": ts,
            "applicant_user_id": application["user_id"],
        }
        insert_slack_event(slack_conn, event_data)

        add_default_reacts(cfg, channel=response["channel"], timestamp=ts)
        add_default_message(cfg, channel=response["channel"], timestamp=ts)

        modal = build_questions_modal_view(application_data=application["data"])
        logger.debug(
            "Saving slack modal response for user %s (outbox_id=%s).",
            application["user_id"],
            outbox_id,
        )

        save_slack_modal_response(
            conn=slack_conn,
            applicant_user_id=application["user_id"],
            thread_ts=ts,
            slack_modal_blocks=json.dumps(modal),
        )
        kos_api_client.mark_outbox(outbox_id)
        return response

    except Exception as exc:
        logger.exception("Failed to process outbox_id %s.", outbox_id)
        kos_api_client.mark_outbox(outbox_id, last_error=str(exc)[:1000])
        return {f"Submission Failed {exc}"}


def get_application_from_outbox(kos_api_client: kos_api.KosApiClient, outbox_id: int = None):
    if outbox_id is None:
        logger.debug("Fetching next outbox item.")
        row = kos_api_client.get_next_outbox()
    else:
        logger.debug("Fetching outbox by id %s.", outbox_id)
        row = kos_api_client.get_outbox(outbox_id)

    return row
