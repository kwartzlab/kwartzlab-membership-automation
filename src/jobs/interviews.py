import json
import logging

import services.kos_api as kos_api
from core import config
from services.kos_api import mark_outbox_on_error
from services.slack.slack import (
    add_default_message,
    add_default_reacts,
    build_questions_modal_view,
    insert_slack_event,
    post_application,
    save_slack_modal_response,
)

logger = logging.getLogger(__name__)


def process_one(
    kos_api_client: kos_api.KosApiClient,
    slack_conn,
    cfg: config.Config,
    outbox_id: int = None,
    form_submission_id: int = None,
):
    application = get_application_from_outbox(
        kos_api_client, outbox_id=outbox_id, form_submission_id=form_submission_id
    )
    if not application:
        return None
    outbox_id = application.get("outbox_id")
    try:
        logger.info(
            "Processing submission %s (outbox_id=%s).",
            application.get("form_submission_id", form_submission_id),
            outbox_id,
        )
        response = post_application(
            cfg=cfg,
            application_data=application["data"],
        )
        ts = response["ts"]
        event_data = {
            "thread_ts": ts,
            "form_submission_id": application.get("form_submission_id", form_submission_id),
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
            form_submission_id=str(application.get("form_submission_id", form_submission_id)),
            slack_modal_blocks=json.dumps(modal),
        )
        if outbox_id:
            kos_api_client.mark_outbox(outbox_id)
        return response

    except Exception as exc:
        mark_outbox_on_error(kos_api_client, outbox_id, exc, log=logger)
        raise


def get_application_from_outbox(
    kos_api_client: kos_api.KosApiClient, outbox_id: int = None, form_submission_id: int = None
):
    if form_submission_id is not None:
        logger.debug("Fetching form submission by id %s.", form_submission_id)
        row = kos_api_client.get_form_submission(form_submission_id)
    elif outbox_id is not None:
        logger.debug("Fetching outbox by id %s.", outbox_id)
        row = kos_api_client.get_outbox(outbox_id)
    else:
        logger.debug("Fetching next outbox item.")
        row = kos_api_client.get_next_outbox()

    return row
