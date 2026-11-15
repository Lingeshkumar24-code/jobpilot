# n8n Workflows

Seven workflow exports are included. Six are importable and usable; one is
intentionally kept inactive.

| File | Schedule / Trigger | Purpose | Status |
|---|---|---|---|
| `daily-digest.json` | Daily 08:00 UTC | Agent runs digest mode for opted-in users | Import and activate |
| `refresh-jobs.json` | Every 6 hours | Fetches fresh listings, re-scores matches | Import and activate |
| `followup-reminder.json` | Daily 09:00 UTC | Suggests follow-ups on stale confirmed apps | Import and activate |
| `application-tracking.json` | Webhook (event) | Scoped run per application-tracking event | Import; triggered by external events |
| `new-job-notification.json` | Webhook (event) | Scoped run per new-job event | Import; triggered by external events |
| `failure-handling.json` | Webhook (error) | Records automation failures in the audit trail | Import; called by other workflows on error |
| `resume-processing.json` | Webhook | ⚠ Intentionally disabled — parsing is synchronous | Import to avoid 404 on stale calls; leave inactive |

## Setup

The API validates signed inbound webhook requests using HMAC-SHA256 and
deduplicates delivery IDs. These exports trigger agent runs; they do not
send email or push notifications.

**Required environment variables on the n8n service:**

| Variable | Description |
|---|---|
| `N8N_WEBHOOK_SECRET` | Must match `N8N_WEBHOOK_SECRET` in the backend `.env` |
| `JOBPILOT_API_URL` | URL of the backend, e.g. `http://backend:8000` in Compose |

The signing code inside each `Sign webhook` node reads these variables at
runtime. The JSON exports contain **no credentials**.

## Importing workflows

1. Open the n8n editor (default: http://localhost:5678).
2. Go to **Workflows → Import from file** and select each JSON file.
3. Set `N8N_WEBHOOK_SECRET` and `JOBPILOT_API_URL` in the n8n service
   environment before activating any workflow.
4. Activate the schedule-based workflows (daily-digest, refresh-jobs,
   followup-reminder). Leave resume-processing **inactive**.

## Security note

Before exposing the n8n editor on a public network, configure n8n's built-in
basic auth or SSO (`N8N_BASIC_AUTH_ACTIVE`, `N8N_BASIC_AUTH_USER`,
`N8N_BASIC_AUTH_PASSWORD`). The local Docker Compose stack defaults to no
editor authentication.

## Live execution status

Workflows have been inspected and validated as importable JSON. Live execution
in a running n8n instance has **not** been verified in this workspace because
the Docker daemon is not available in the current environment.
