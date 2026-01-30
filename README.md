# Kwartzlab Membership Automation

Automates Kwartzlab membership coordinator workflows by syncing kOS membership submissions to Slack, capturing thread activity in SQLite, and sending templated Gmail replies. Threads can also be backed up and stored to Google Drive.

## Features
- Polls kOS form submissions and posts application summaries to a Slack channel.
- Stores Slack thread events (posts, replies, edits, deletes, reactions) in SQLite, with archiving to JSONL locally & to GDrive.
- Message shortcuts and reaction flows to send templated emails via Gmail as the Membership Coordinator account.

## Workflow
1) The poller checks the kOS outbox every `POLL_INTERVAL_SECONDS` and posts new applications to `SLACK_CHANNEL_ID`.
2) Slack Socket Mode listeners capture message and reaction events and persist them to SQLite.
3) Coordinators can send email via:
   - `email_applicant` message shortcut (opens a modal to choose email type and signature).
   - Reactions `:white_check_mark:`, `:leftwards_arrow_with_hook:`, or `:no_entry_sign:` (with a confirmation prompt).
4) Archiving writes a JSONL file to `archives/` and uploads to Drive when `ARCHIVE_GDRIVE_URL` is set.

## Requirements
- Python 3.11+ (Docker image uses Python 3.12-slim).
- Slack app with Socket Mode enabled.
- kOS API base URL and API token.
- Google OAuth client for Gmail/Drive (`credentials.json`).
- A static bearer token for protected API routes (`API_TOKEN`).

## Quick Start (Local)
1) Create a virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Place your Google OAuth client at `credentials.json` in the repo root.

3) Make a copy of `.env.example` and set the values (see `Configuration` below for more info)

4) Source the env: `source {your_env_file}`

5) Run the app:
```bash
python src/main.py
```

The SQLite database (`slack_threads.db`) and tables are created on startup.

## Configuration
Required environment variables:
- `KOS_API_BASE_URL`
- `KOS_API_TOKEN`
- `API_TOKEN` (bearer token for api endpoints)
- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`
- `SLACK_CHANNEL_ID`

Optional environment variables:
- `AUTHORIZED_USERGROUPS` (space-separated Slack usergroup IDs; default: `SDFB4PKGE`, the BoD slack id)
- `AUTHORIZED_USERS` (space-separated Slack IDs, no default)
- `KOS_API_TIMEOUT_SECONDS` (default: `10`)
- `POLL_INTERVAL_SECONDS` (default: `30`)
- `SQLITE_DB_PATH` (default: `slack_threads.db`, resolved relative to project root)
- `CREDENTIALS_FILE` (default: `credentials.json`)
- `TOKEN_FILE` (default: `token.json`)
- `ARCHIVE_GDRIVE_URL` (Drive folder URL or folder ID)
- `ENVIRONMENT` (default: `development`)
- `PROJECT_ROOT` (override project root for relative paths)
- `PORT` (default: `8080`)
- `DEBUG` (`true`/`false`)
- `LOG_LEVEL` (default: `INFO`)
- `LOG_FILE` (optional path to log file)
- `LOG_FILE_LEVEL` (default: `DEBUG`)
- `LOG_RETENTION_DAYS` (default: `7`)

## Slack App Setup
1) Enable **Socket Mode** and generate an app-level token (`SLACK_APP_TOKEN`).
2) Create a bot token (`SLACK_BOT_TOKEN`) and install the app to your workspace.
3) Enable **Interactivity & Shortcuts**.
4) Create **Message Shortcuts** with the following callback IDs:
   - `email_applicant`
   - `archive_thread`
5) Subscribe to bot events (at minimum):
   - `app_mention`
   - `message.channels` (or `message.groups` if the channel is private)
   - `reaction_added`
   - `reaction_removed`
6) Add bot token scopes (minimum used in code):
   - `app_mentions:read`
   - `channels:history` (or `groups:history` for private channels)
   - `reactions:read`
   - `reactions:write`
   - `chat:write`
   - `users:read`
   - `usergroups:read`

Set `SLACK_CHANNEL_ID` to the target channel. All events are filtered to that channel.

## Gmail + Drive OAuth
The app uses Gmail and Drive scopes:
- `gmail.send`
- `drive.file`

On first run it opens a local OAuth flow and writes `token.json`. If you run in Docker or a headless environment, complete the OAuth flow once locally and mount `credentials.json` and `token.json` into the container.

## API Endpoints
Protected routes require `Authorization: Bearer $API_TOKEN`.
Currently the API Token is a static app token set in the env file.r

Routes:
- `GET /health`
- `POST /process-form-outbox/{outbox_id}`
- `POST /process-form-submission/{form_submission_id}`
- `POST /email/{user_id}/acceptance`
- `POST /email/{user_id}/return_visit`
- `POST /email/{user_id}/rejection`

Example:
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  -X POST "http://localhost:8080/process-form-outbox/123"
```

## Docker
The repo includes `dockerfile`, `compose.yaml`, and `compose.prod.yaml`.

**Note**: You must run locally at least once to generate the `token.json` file.

### Docker Compose

Start the app:
```bash
docker compose up --build -d
```

### Docker Compose (Prod)
Use the production override to pull the published image (always pulls latest for the tag):
```bash
docker compose -f compose.prod.yaml up -d
```

### Docker CLI
```bash
docker build -t kwartzlab-membership-automation .
docker run --env-file .env --name kwartzlab-membership-automation \
  --network kos-base_data-network \
  -v "$PWD/logs:/app/logs" \
  -v "$PWD/credentials.json:/app/credentials.json" \
  -v "$PWD/token.json:/app/token.json" \
  -v "$PWD/database/slack_threads.db:/app/slack_threads.db" \
  -v "$PWD/archives:/app/archives" \
  kwartzlab-membership-automation
```

### Mounting in Docker
Certain files and folder should be mounted in Docker, instead of being part of the docker persistant volume.
By default, the `compose.yaml` file mounts all recommended paths with project relative paths.

The only mounted paths required are `credentials.json` and `token.json`, the rest can safely ignored/unmounted.
## Notes
- This project complements kOS but does not directly integrate with its database.
