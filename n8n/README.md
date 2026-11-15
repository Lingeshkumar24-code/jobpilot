# n8n Workflows

Three importable workflow exports are currently included:

- `refresh-jobs.json` — scheduled public-source refresh every six hours.
- `daily-digest.json` — daily digest agent run.
- `followup-reminder.json` — daily follow-up agent run.

The API validates signed inbound webhook requests and deduplicates delivery
IDs. These exports trigger agent runs; they do not send email or notifications.
The resume-processing export is intentionally disabled because resume parsing
is synchronous in the API. New-job and application-tracking events create
scoped agent runs, but do not send push/email notifications or change
application statuses. Failure reports are stored in the audit trail; automatic
retries and administrator notification are not configured. n8n editor
authentication and production access controls must be configured before
exposing the editor.

Import JSON through the n8n UI. Configure `N8N_WEBHOOK_SECRET` and
`JOBPILOT_API_URL` in the n8n service environment. The signing code reads the
secret at runtime; exports contain no credentials.
