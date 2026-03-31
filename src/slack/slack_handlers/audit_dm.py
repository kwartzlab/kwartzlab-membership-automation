import asyncio
import logging

from slack_membership_audit import (
    SlackAuditBuckets,
    SlackAuditConfig,
    _load_kos_indexes,
    _load_slack_candidates,
    _run_membership_audit,
    load_slack_audit_overrides,
)

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_SECTION = 10
_AUDIT_OVERRIDES_FILE = "slack_audit_overrides.json"


def audit_dm_help_text() -> str:
    return "Audit DM commands:\n- `audit slack`: audit Slack membership against kOS"


async def handle_audit_dm_command(text: str, *, user_id: str, say, cfg, runtime) -> bool:
    lowered = text.lower().strip()

    if lowered == "audit slack":
        await say("Running Slack membership audit, this may take a moment...")
        slack_audit_cfg = SlackAuditConfig(
            kos_api_base_url=cfg.kos_api_base_url,
            kos_api_token=cfg.kos_api_token,
            kos_api_timeout_seconds=cfg.kos_api_timeout_seconds,
            slack_bot_token=cfg.slack_bot_token,
            include_deleted_slack_users=False,
            overrides_file=_AUDIT_OVERRIDES_FILE,
        )
        buckets, total_candidates = await asyncio.to_thread(_run_audit, slack_audit_cfg)
        await say(
            blocks=_build_audit_blocks(buckets, total_candidates=total_candidates),
            text="Slack audit complete.",
        )
        return True

    if lowered.startswith("audit"):
        await say("Unknown audit command. Use `audit slack` to audit Slack membership.")
        return True

    return False


def _run_audit(cfg: SlackAuditConfig) -> tuple:
    _, indexes = _load_kos_indexes(cfg)
    overrides = load_slack_audit_overrides(cfg.overrides_file)
    slack_members, candidates = _load_slack_candidates(cfg)
    buckets = _run_membership_audit(candidates, indexes=indexes, overrides=overrides)
    return buckets, len(candidates)


def _format_non_active_line(row: dict) -> str:
    slack_user_id = row.get("slack_user_id")
    slack_email = row.get("slack_email") or "no email"
    kos_name = row.get("kos_name") or "unknown"
    kos_status = row.get("kos_status") or "unknown"
    mention = f"<@{slack_user_id}>" if slack_user_id else kos_name
    return f"{mention} (`{slack_email}`) → kOS: {kos_name} [{kos_status}]"


def _format_unmapped_line(row: dict) -> str:
    slack_user_id = row.get("slack_user_id")
    slack_name = row.get("slack_name") or row.get("slack_display_name") or "unknown"
    slack_email = row.get("slack_email") or "no email"
    mention = f"<@{slack_user_id}>" if slack_user_id else slack_name
    return f"{mention} (`{slack_email}`)"


def _format_low_confidence_line(row: dict) -> str:
    slack_user_id = row.get("slack_user_id")
    slack_email = row.get("slack_email") or "no email"
    kos_name = row.get("kos_name") or "unknown"
    match_source = row.get("match_source") or "unknown"
    mention = f"<@{slack_user_id}>" if slack_user_id else kos_name
    return f"{mention} (`{slack_email}`) → kOS: {kos_name} [{match_source}]"


def _build_section(title: str, rows: list[dict], formatter, max_results: int) -> list[dict]:
    if not rows:
        return []
    lines = [formatter(row) for row in rows[:max_results]]
    text = f"*{title}* ({len(rows)})\n" + "\n".join(lines)
    remaining = len(rows) - max_results
    if remaining > 0:
        text += f"\n_...and {remaining} more_"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def _build_audit_blocks(buckets: SlackAuditBuckets, *, total_candidates: int) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Slack membership audit*\n"
                    f"Users checked: {total_candidates} | "
                    f"Mapped: {len(buckets.mapped_rows)} | "
                    f"Low confidence: {len(buckets.low_confidence_rows)} | "
                    f"Unmapped: {len(buckets.unmapped_rows)} | "
                    f"Ambiguous: {len(buckets.ambiguous_rows)} | "
                    f"Non-active: {len(buckets.mapped_non_active_kos_rows)}"
                ),
            },
        }
    ]

    blocks += _build_section(
        "Should not be on Slack (non-active kOS status)",
        buckets.mapped_non_active_kos_rows,
        _format_non_active_line,
        MAX_RESULTS_PER_SECTION,
    )
    blocks += _build_section(
        "Unknown users (no kOS match)",
        buckets.unmapped_rows,
        _format_unmapped_line,
        MAX_RESULTS_PER_SECTION,
    )
    blocks += _build_section(
        "Low confidence matches (review needed)",
        buckets.low_confidence_rows,
        _format_low_confidence_line,
        MAX_RESULTS_PER_SECTION,
    )
    blocks += _build_section(
        "Ambiguous matches (multiple kOS candidates)",
        buckets.ambiguous_rows,
        _format_unmapped_line,
        MAX_RESULTS_PER_SECTION,
    )

    if not any(
        [
            buckets.mapped_non_active_kos_rows,
            buckets.unmapped_rows,
            buckets.low_confidence_rows,
            buckets.ambiguous_rows,
        ]
    ):
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "All Slack users are mapped to active kOS members.",
                },
            }
        )

    return blocks
