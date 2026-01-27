# Kwartzlab Membership Automation

Automates membership coordinator workflows for Kwartzlab. The app listens to Slack events, stores thread activity in SQLite, and supports email workflows plus optional thread archiving to Google Drive.

## Features
- Slack event capture (posts, replies, edits, deletes, reactions) into SQLite.
- Slack shortcuts for email workflows and thread archiving.
- Gmail integration for templated membership emails.
- Optional Google Drive upload for archived thread JSONL files.

## Requirements
- Python 3.11+
- Slack app tokens (bot + app token)
- kOS API credentials
- Gmail API credentials (`credentials.json`) and token cache (`token.json`)

## Setup (Local)
1) Create a virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Ensure you have OAuth credentials for Gmail/Drive:
   - Place your OAuth client in `credentials.json` at the repo root.
   - The app will create/update `token.json` after the first auth flow.

3) Configure environment variables (see `Environment` below). You can edit `.env` directly.

4) Run the app:
```bash
python src/main.py
```

## Setup (Slack App)
You will need a Slack app with Socket Mode enabled:
1) Create a Slack app and enable Socket Mode.
2) Create a bot token and app-level token.
3) Set the bot token as `SLACK_BOT_TOKEN` and the app-level token as `SLACK_APP_TOKEN`.
4) Grant the app the permissions needed for reading messages/reactions and using shortcuts.
5) Install the app to your workspace and set `SLACK_CHANNEL_ID`.

## Environment
Minimum required variables:
- `KOS_API_BASE_URL`
- `KOS_API_TOKEN`
- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`
- `SLACK_CHANNEL_ID`

Optional variables:
- `ARCHIVE_GDRIVE_URL` (Google Drive folder URL or folder ID)
- `SQLITE_DB_PATH` (default: `slack_threads.db`)
- `CREDENTIALS_FILE` (default: `credentials.json`)
- `TOKEN_FILE` (default: `token.json`)
- `POLL_INTERVAL_SECONDS` (default: `30`)
- `DEBUG` (`true`/`false`)
- `PORT` (default: `8080`)

## Slack Shortcuts
- `email_applicant`: choose an email template and send via Gmail.
- `archive_thread`: write a JSONL archive to `archives/` and optionally upload to Drive.

## Google Drive Archiving
Set `ARCHIVE_GDRIVE_URL` to a folder URL or folder ID. On first use, the app will open a local OAuth flow to grant Drive access and store credentials in `token.json`.

## Docker
The repo includes a `dockerfile` and `compose.yaml`.

### Docker Compose
`compose.yaml` attaches the container to the external network `kos-base_data-network`. Create it once if needed:
```bash
docker network create kos-base_data-network
```

Start the app:
```bash
docker compose up --build -d
```

### Docker CLI
```bash
docker build -t kwartzlab-membership-automation .
docker run --env-file .env --name kwartzlab-membership-automation \
  --network kos-base_data-network \
  kwartzlab-membership-automation
```

### Credentials in Docker
By default, `credentials.json` and `token.json` are baked into the image at build time. If you want the OAuth token to persist across rebuilds or be updated at runtime, mount them as volumes:
```bash
docker run --env-file .env --name kwartzlab-membership-automation \
  --network kos-base_data-network \
  -v "$PWD/credentials.json:/app/credentials.json" \
  -v "$PWD/token.json:/app/token.json" \
  kwartzlab-membership-automation
```

## Project Structure
- `src/` app code
- `archives/` local thread archives
- `credentials.json` Gmail/Drive OAuth client
- `token.json` OAuth token cache

## Notes
- This project complements kOS but does not directly integrate with its database.
