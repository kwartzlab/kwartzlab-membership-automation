import json


def register_message_handler(app, cfg, runtime, queue):
    @app.event("message")
    async def on_message(event, body):
        if event.get("subtype") == "bot_message":
            return

        if getattr(cfg, "slack_channel_id", None):
            if event.get("channel") != cfg.slack_channel_id:
                return

        if event.get("subtype") in (None, "message_replied"):
            event_type = "post" if not event.get("thread_ts") else "reply"
            thread_ts = event.get("thread_ts") or event.get("ts")
            parent_message = event.get("thread_ts") if event.get("thread_ts") else None
            text = event.get("text", "")
            user_id = event.get("user")

        elif event.get("subtype") == "message_changed":
            message = event["message"]

            event_type = "edit"
            thread_ts = message.get("thread_ts") or message["ts"]
            parent_message = message["ts"]
            text = message.get("text", "")
            user_id = message.get("user")

        elif event.get("subtype") == "message_deleted":
            message = event["previous_message"]

            event_type = "delete"
            thread_ts = message.get("thread_ts") or event["deleted_ts"]
            parent_message = event.get("deleted_ts")
            text = message.get("text", "")
            user_id = message.get("user")

        else:
            return

        event_data = {
            "thread_ts": thread_ts,
            "user_id": user_id,
            "user_name": runtime.cache_manager.users_cache.get(user_id, user_id),
            "event": event_type,
            "message": text,
            "parent_message": parent_message,
            "raw_response": json.dumps(body),
            "timestamp": event.get("ts"),
            "applicant_user_id": None,
        }
        await queue.put(event_data)

