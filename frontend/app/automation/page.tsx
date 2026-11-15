"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Empty,
  Notice,
  PageHeader,
  Spinner,
  StatusBadge,
  formatDate,
} from "@/components/ui";
import { api, ApiError, type SystemStatus, type Workflow } from "@/lib/api";

export default function AutomationPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listWorkflows(), api.systemStatus().catch(() => null)])
      .then(([items, system]) => {
        setWorkflows(items);
        setStatus(system);
      })
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to see automation workflows."
            : err instanceof Error
              ? err.message
              : "Could not load workflows",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  async function trigger(key: string) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const result = await api.triggerWorkflow(key);
      setNotice(result.message);
      setWorkflows(await api.listWorkflows());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not trigger the workflow");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Automation Center"
        description="n8n-compatible workflows trigger the same agent. Inbound webhooks are signed with HMAC-SHA256; replay deliveries are ignored. No workflow can submit without approval."
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}

      <Card title="Connection">
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <p className="text-xs text-muted">n8n webhook base</p>
            <p className="font-mono text-xs text-paper">
              {status?.n8n_configured ? "configured (N8N_WEBHOOK_BASE_URL)" : "not configured"}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted">Inbound endpoint</p>
            <p className="font-mono text-xs text-paper">POST /api/v1/automation/webhooks/&lt;workflow-key&gt;</p>
          </div>
        </div>
        <p className="mt-3 text-xs text-muted">
          Required headers: <span className="font-mono">X-JobPilot-Signature: sha256=&lt;hmac&gt;</span> and optionally{" "}
          <span className="font-mono">X-JobPilot-Delivery</span> for idempotency. If the secret is missing, the backend
          refuses unsigned requests with HTTP 503 rather than trusting them.
        </p>
      </Card>

      {loading ? <Spinner label="Loading workflows…" /> : null}

      {!loading && !workflows.length ? <Empty title="No workflows seeded" /> : null}

      <div className="space-y-3">
        {workflows.map((workflow) => (
          <Card
            key={workflow.id}
            title={workflow.name}
            action={
              <span
                className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase ${
                  workflow.is_active ? "border-signal/60 text-signal" : "border-line text-muted"
                }`}
              >
                {workflow.is_active ? "active" : "disabled"}
              </span>
            }
          >
            <p className="text-sm text-muted">{workflow.description}</p>
            <p className="mt-2 text-xs text-muted">
              key <span className="font-mono text-paper">{workflow.key}</span> · last run{" "}
              {formatDate(workflow.last_run_at)} · status {workflow.last_status ?? "—"}
            </p>
            <div className="mt-3">
              <Button
                size="sm"
                variant="primary"
                onClick={() => trigger(workflow.key)}
                disabled={Boolean(busy) || !workflow.is_active}
              >
                {busy === workflow.key ? "Triggering…" : "Trigger now"}
              </Button>
            </div>
          </Card>
        ))}
      </div>

      <Card title="Setup">
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
          <li>Import the workflow JSON files from <span className="font-mono text-paper">automation/n8n</span> into n8n.</li>
          <li>
            Set <span className="font-mono text-paper">N8N_WEBHOOK_BASE_URL</span> and{" "}
            <span className="font-mono text-paper">N8N_WEBHOOK_SECRET</span> on the API.
          </li>
          <li>Use the same secret in the n8n HTTP Request node's signature header.</li>
          <li>Schedule a daily digest and a job refresh; both create ordinary agent runs you can inspect.</li>
        </ol>
      </Card>
    </div>
  );
}
