---
name: bablomat-daily-digest
description: "Use when preparing daily Bablomat message digests."
metadata:
  hermes:
    related_skills: [telegram-group-monitoring, shared-tasks-reminders, hermes-agent]
---

# Daily БАБЛОМАТ digest

## User preference

**Current authorization:** the owner cancelled the scheduled daily Bablomat digest. Keep shared-task `TASK_ID` cancelled and its former cron `673c2a457246` absent. Do not recreate this report schedule without a new explicit request. Continue ordinary accounting polling and replies; the digest script and historical exports remain available on demand. The10:00/24hour procedure below is retained implementation context, not an active scheduling request.

The owner requests a daily digest at **10:00 Europe/Moscow**, sent to his private Telegram chat `OWNER_USER_ID`. Cover messages in БАБЛОМАТ (`ACCOUNTING_CHAT_ID`) over the preceding **24 hours**, together with the assistant's actual replies. This is a requested workflow, not evidence that a cron job exists.

## Procedure

- Load the related monitoring and Hermes skills before implementation/configuration. Inspect existing jobs first and update a matching digest rather than creating duplicates.
- When asked to inspect a delivered digest, first locate its saved TXT/JSON artifact for the exact delivered period; do not rerun a moving-window script and substitute a different interval. Resolve any specifically linked source message before expanding to the whole digest.
- Read active incoming rows from state.db and outgoing delivery receipts/logs. Join by exact chat ID and platform message ID, never chronological proximity.
- Pair each reply with its complete original and Telegram links. Include corrections, mark struck/superseded answers, and distinguish unanswered messages from messages needing no response.
- Preserve source wording, dates and money values verbatim. Do not substitute a reconstructed accounting template. Presentation headings use day/month plus Russian weekday abbreviation, without year.
- If the owner asks to show messages as quotations, use visible blockquotes with the complete original text, a separate source link and Moscow receipt time. Preserve years and formatting inside the quoted source; the short-date preference applies to presentation headings, not rewriting evidence. Do not include bot answers unless requested. Label photo/audio records as attachments instead of inventing their contents.
- Treat unequal participant-message and bot-reply counts as a question to investigate, not proof of failure: counts can include chatter and attachments requiring no reply. Read the linked report and its ledger status before explaining an unanswered cash report; scheduler success alone does not prove every report was parsed or answered.
- Deduplicate/count in code and save complete JSON/Markdown exports. Attach the full export if an inline digest is cumbersome.
- Filter replies by verified delivery time, not just source timestamps. If older receipts lack delivery timestamps and logs cannot supply them, disclose the coverage limitation. New receipt schemas should retain destination, source ID, returned bot ID and delivery timestamp together.
- Test and exercise the actual digest script against real stored data, then verify the active schedule and private delivery target before claiming operation. Saving a preference is not enabling a schedule.
