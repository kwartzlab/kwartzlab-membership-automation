import asyncio
import json
import logging

import services.db as db
from services.slack import slack as slack_service

logger = logging.getLogger(__name__)


def register_modal_handler(app, cfg, runtime):
    @app.action("view_application_questions")
    async def handle_view_questions(ack, body, client, logger):
        await ack()

        try:
            thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
            if not thread_ts:
                # Fallback: try container message
                thread_ts = body.get("container", {}).get("message_ts")

            if not thread_ts:
                logger.warning("No thread_ts/ts found in action body.")
                return

            modal = None
            form_submission_id = None
            with runtime.slack_db_engine.begin() as conn:
                modal = db.get_modal_blocks_payload_by_thread_ts(conn, thread_ts)
                if not modal:
                    form_submission_id = db.get_form_submission_id_by_thread_ts(conn, thread_ts)
            if not modal and form_submission_id:
                submission = await asyncio.to_thread(
                    runtime.kos_api_client.get_form_submission,
                    int(form_submission_id),
                )
                if submission:
                    application_data = submission.get("data", submission)
                else:
                    application_data = None
                if application_data:
                    modal = slack_service.build_questions_modal_view(application_data=application_data)
                    with runtime.slack_db_engine.begin() as conn:
                        applicant_user_id = db.get_applicant_user_id_by_thread_ts(conn, thread_ts)
                        if applicant_user_id:
                            db.insert_interview_answers_slack_modal_row(
                                conn,
                                applicant_user_id=applicant_user_id,
                                thread_ts=thread_ts,
                                form_submission_id=str(form_submission_id),
                                slack_modal_blocks=json.dumps(modal, ensure_ascii=True),
                            )

            if not modal:
                await client.views_open(
                    trigger_id=body["trigger_id"],
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Application"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": "Couldn’t find application data for this thread."},
                            }
                        ],
                    },
                )
                return

            await client.views_open(trigger_id=body["trigger_id"], view=modal)

        except Exception as exc:
            logger.exception("Failed to open questions modal: %s", exc)
            # Avoid leaking details to users; just log server-side.
            try:
                await client.views_open(
                    trigger_id=body["trigger_id"],
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Error"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": "Something went wrong opening the modal."},
                            }
                        ],
                    },
                )
            except Exception:
                logger.debug("Failed to open error modal.")
