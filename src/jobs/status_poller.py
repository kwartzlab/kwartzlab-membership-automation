import asyncio
import logging
from calendar import monthrange
from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import services.db as db
from services.slack.slack import post_status_change, post_upcoming_statuses_digest

logger = logging.getLogger(__name__)

# 8:00 AM EST = 13:00 UTC
_TRIGGER_HOUR_UTC = 13


async def status_changes_loop(cfg, kos_api_client, slack_engine):
    while True:
        try:
            await asyncio.to_thread(_process_status_changes, cfg, kos_api_client, slack_engine)
        except asyncio.CancelledError:
            logger.info("Status changes loop cancelled.")
            raise
        except Exception:
            logger.exception("Error processing status changes.")

        await asyncio.sleep(cfg.poll_interval_seconds)


def _process_status_changes(cfg, kos_api_client, slack_engine):
    with slack_engine.begin() as conn:
        statuses = db.poll_user_status_changes(conn, kos_api_client)

    slack_client = WebClient(token=cfg.slack_bot_token)

    for status in statuses:
        if status.get("status") in cfg.ignored_status_types:
            logger.debug("Skipping ignored status type %r for user %s.", status["status"], status["user_id"])
            continue
        try:
            user = kos_api_client.get_user(status["user_id"])
            updated_by_user = kos_api_client.get_user(status["updated_by"]) if status.get("updated_by") else None
            slack_user_id = _lookup_slack_id(slack_client, user)
            post_status_change(cfg, status, user, slack_user_id, updated_by_user)
            logger.info("Posted status change id=%s user=%s status=%s.", status["id"], status["user_id"], status["status"])
        except Exception:
            logger.exception("Failed to post status change id=%s.", status.get("id"))


async def upcoming_statuses_loop(cfg, kos_api_client):
    while True:
        now = datetime.now(timezone.utc)
        next_trigger, days = _next_upcoming_trigger(now)
        sleep_seconds = (next_trigger - now).total_seconds()
        logger.debug("Next upcoming statuses digest at %s (in %.0fs, days=%d).", next_trigger.isoformat(), sleep_seconds, days)

        await asyncio.sleep(sleep_seconds)

        try:
            await asyncio.to_thread(_post_upcoming_digest, cfg, kos_api_client, days)
        except asyncio.CancelledError:
            logger.info("Upcoming statuses loop cancelled.")
            raise
        except Exception:
            logger.exception("Error posting upcoming statuses digest.")

        # Sleep 1 hour after firing to avoid double-posting within the same trigger window
        await asyncio.sleep(3600)


def _post_upcoming_digest(cfg, kos_api_client, days: int):
    statuses = kos_api_client.get_upcoming_user_statuses(days=days)
    if cfg.ignored_status_types:
        statuses = [s for s in statuses if s.get("status") not in cfg.ignored_status_types]

    if not statuses:
        logger.debug("No upcoming statuses to post.")
        return

    user_ids = {s["user_id"] for s in statuses}
    users = {uid: kos_api_client.get_user(uid) for uid in user_ids}

    slack_client = WebClient(token=cfg.slack_bot_token)
    slack_id_by_kos_id = {uid: _lookup_slack_id(slack_client, users.get(uid)) for uid in user_ids}

    post_upcoming_statuses_digest(cfg, statuses, users, slack_id_by_kos_id)
    logger.info("Posted upcoming statuses digest (%d entries, days=%d).", len(statuses), days)


def _lookup_slack_id(slack_client: WebClient, user: dict | None) -> str | None:
    if not user or not user.get("email"):
        return None
    try:
        resp = slack_client.users_lookupByEmail(email=user["email"])
        return resp["user"]["id"]
    except SlackApiError:
        return None


def _next_upcoming_trigger(now: datetime) -> tuple[datetime, int]:
    """Return (next_trigger_utc, days_param) for the upcoming digest schedule.

    Triggers fire at _TRIGGER_HOUR_UTC on:
    - The 25th of each month  (days=7, ~1 week preview to catch EoM changes)
    - The 2nd-to-last day of each month  (days=2, final reminder)
    """
    year, month = now.year, now.month
    candidates = _trigger_candidates(year, month) + _trigger_candidates(
        *(_next_month(year, month))
    )
    future = [(dt, d) for dt, d in candidates if dt > now]
    return min(future, key=lambda x: x[0])


def _trigger_candidates(year: int, month: int) -> list[tuple[datetime, int]]:
    days_in_month = monthrange(year, month)[1]
    second_to_last = days_in_month - 1
    return [
        (datetime(year, month, 25, _TRIGGER_HOUR_UTC, 0, 0, tzinfo=timezone.utc), 7),
        (datetime(year, month, second_to_last, _TRIGGER_HOUR_UTC, 0, 0, tzinfo=timezone.utc), 2),
    ]


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)
