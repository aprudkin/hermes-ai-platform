# Private task register boundary

The live `shared-tasks/tasks.json` belongs to the protected active profile, not
Git. It includes private tasks, source/delivery routes, history, real job IDs and
reminder progress. Recover it from the private backup; never overwrite it with
an empty example or recreate its cron jobs from a repository name match.

`tasks.example.json` is an explicitly synthetic **empty schema1 example**, not
an export of the current task list. Root fields are schema_version, list_name,
created_at, updated_at and tasks. A task can carry id, title, assignee, status,
created_at, due_text, schedule, cron_job_id, reminder_route, source_chat and
history; deterministic runners additionally own their documented nested state.

Writers must lock the stable `tasks.json.lock`, re-read current contents under
lock, preserve unrelated tasks and atomically replace the file. Preserve sent,
inflight and uncertain intents through recovery; no blind retries or new job
creation as a substitute for reconciliation.

Repository publication changes no schedule or destination. Event reminders and
meter reminders retain their explicit private routes; do not silently fall back
to the owner's DM. Their vetted operational guidance is in
[shared-tasks-reminders](../../skills/productivity/shared-tasks-reminders/SKILL.md)
and the [meter runner](../meter_reminders/README.md).
