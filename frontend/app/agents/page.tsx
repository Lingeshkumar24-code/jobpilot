"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Notice,
  PageHeader,
  Spinner,
  StatusBadge,
  formatDate,
  timeAgo,
} from "@/components/ui";
import {
  api,
  ApiError,
  type AgentRun,
  type ApplicationDetail,
} from "@/lib/api";

type Prompt = {
  application_id?: string;
  job?: { title?: string; company?: string; url?: string };
  status?: string;
  warnings?: string[];
  missing_required?: string[];
  resume?: { filename?: string } | null;
  instruction?: string;
};

export default function AgentsPage() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [goal, setGoal] = useState("Find fresh Python backend roles and prepare one application for my review");
  const [prepare, setPrepare] = useState(true);
  const [limit, setLimit] = useState("5");
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [approvalRun, setApprovalRun] = useState<AgentRun | null>(null);
  const [approvalDetail, setApprovalDetail] = useState<ApplicationDetail | null>(null);

  async function load() {
    const result = await api.listAgentRuns();
    setRuns(result.runs);
  }

  useEffect(() => {
    load()
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to run agents."
            : err instanceof Error
              ? err.message
              : "Could not load agent runs",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  async function start() {
    setBusy("start");
    setError(null);
    setNotice(null);
    try {
      const run = await api.startAgentRun(goal.trim(), prepare, Number(limit) || 5);
      setRuns((current) => [run, ...current]);
      if (run.status === "awaiting_approval") {
        setNotice("The agent paused. Review the prepared application, then approve or decline it.");
      } else {
        setNotice(`Run finished with status “${run.status}”.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the agent");
    } finally {
      setBusy(null);
    }
  }

  async function openApproval(run: AgentRun) {
    const prompt = (run.interrupt_payload ?? {}) as Prompt;
    if (!prompt.application_id) return;
    setBusy(run.id);
    setError(null);
    try {
      setApprovalDetail(await api.getApplication(prompt.application_id));
      setApprovalRun(run);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the prepared application");
    } finally {
      setBusy(null);
    }
  }

  async function approveAndResume() {
    if (!approvalRun || !approvalDetail) return;
    setBusy("approve");
    setError(null);
    try {
      const requested = await api.requestApproval(approvalDetail.id);
      const approved = await api.approve(approvalDetail.id, requested.approval_token);
      const run = await api.resumeAgentRun(approvalRun.id, true, approvalDetail.id, approved.proof);
      setRuns((current) => current.map((item) => (item.id === run.id ? run : item)));
      setApprovalRun(null);
      setApprovalDetail(null);
      setNotice(
        run.result?.submission_outcome === "CONFIRMED"
          ? "Submitted and confirmed by the target site."
          : `Run finished. Submission outcome: ${String(run.result?.submission_outcome ?? "not submitted")}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve and resume the run");
    } finally {
      setBusy(null);
    }
  }

  async function decline(run: AgentRun) {
    setBusy(run.id);
    setError(null);
    try {
      const updated = await api.resumeAgentRun(
        run.id,
        false,
        ((run.interrupt_payload ?? {}) as Prompt).application_id,
      );
      setRuns((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setNotice("Submission declined. The run finished without applying.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resume the run");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="AI Agents"
        description="A checkpointed LangGraph workflow with 9 visible steps. It stops at a human approval interrupt before any submission and never bypasses a CAPTCHA or login."
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}

      <Card title="Start a run">
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            start();
          }}
        >
          <Input value={goal} onChange={(event) => setGoal(event.target.value)} aria-label="Agent goal" />
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={prepare} onChange={(event) => setPrepare(event.target.checked)} />
              Prepare an application and pause for approval
            </label>
            <label className="flex items-center gap-2">
              Match limit
              <Input
                value={limit}
                onChange={(event) => setLimit(event.target.value.replace(/[^0-9]/g, ""))}
                className="w-16"
                aria-label="Match limit"
              />
            </label>
            <Button type="submit" variant="primary" size="sm" disabled={busy === "start" || goal.trim().length < 3}>
              {busy === "start" ? "Running…" : "Start agent"}
            </Button>
          </div>
          <p className="text-xs text-muted">
            Runs use an in-memory LangGraph checkpointer. If the API restarts while waiting for approval, the run cannot
            be resumed and must be started again. That limitation is deliberate: no silent replay of a submission.
          </p>
        </form>
      </Card>

      {loading ? <Spinner label="Loading runs…" /> : null}

      {!loading && !runs.length ? (
        <Empty title="No agent runs yet">Start a run above. Every step is persisted with a redacted trace.</Empty>
      ) : null}

      <div className="space-y-4">
        {runs.map((run) => {
          const prompt = (run.interrupt_payload ?? {}) as Prompt;
          return (
            <Card key={run.id} title={run.goal} action={<StatusBadge status={run.status} />}>
              <p className="text-xs text-muted">
                started {formatDate(run.started_at ?? run.created_at)}
                {run.completed_at ? ` · finished ${formatDate(run.completed_at)}` : ""} · thread{" "}
                <span className="font-mono">{run.thread_id.slice(0, 10)}</span>
              </p>

              {run.status === "awaiting_approval" ? (
                <div className="mt-3 rounded border border-amber/40 bg-ink px-3 py-3">
                  <p className="text-sm text-amber">Waiting for your explicit approval</p>
                  <p className="mt-1 text-xs text-muted">
                    {prompt.job?.title} — {prompt.job?.company} · application status{" "}
                    {(prompt.status ?? "").replaceAll("_", " ").toLowerCase()}
                  </p>
                  {(prompt.missing_required ?? []).length ? (
                    <p className="mt-1 text-xs text-danger">
                      Missing required fields: {(prompt.missing_required ?? []).join(", ")}
                    </p>
                  ) : null}
                  {(prompt.warnings ?? []).length ? (
                    <p className="mt-1 text-xs text-amber">{(prompt.warnings ?? []).join(" ")}</p>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="primary" onClick={() => openApproval(run)} disabled={Boolean(busy)}>
                      Review & approve
                    </Button>
                    {prompt.application_id ? (
                      <Link href={`/assistant?application=${prompt.application_id}`}>
                        <Button size="sm" variant="ghost">
                          Open in assistant
                        </Button>
                      </Link>
                    ) : null}
                    <Button size="sm" variant="danger" onClick={() => decline(run)} disabled={Boolean(busy)}>
                      Decline
                    </Button>
                  </div>
                </div>
              ) : null}

              {run.error ? (
                <div className="mt-3">
                  <Notice>{run.error}</Notice>
                </div>
              ) : null}

              {run.result ? (
                <div className="mt-3 rounded border border-line bg-ink px-3 py-2 text-xs">
                  <p className="text-muted">Result</p>
                  <pre className="mt-1 overflow-auto whitespace-pre-wrap text-paper">
                    {JSON.stringify(run.result, null, 2)}
                  </pre>
                </div>
              ) : null}

              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-muted">
                  Trace ({run.steps.length} step{run.steps.length === 1 ? "" : "s"})
                </summary>
                <ol className="mt-2 space-y-1.5">
                  {run.steps.map((step, index) => (
                    <li key={`${step.node}-${index}`} className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                      <span className={step.status === "error" ? "text-danger" : "text-paper"}>
                        {index + 1}. {step.label}
                        {step.detail ? ` — ${step.detail}` : ""}
                      </span>
                      <span className="text-muted">{timeAgo(step.at)}</span>
                    </li>
                  ))}
                  {!run.steps.length ? <li className="text-xs text-muted">No steps recorded yet.</li> : null}
                </ol>
              </details>
            </Card>
          );
        })}
      </div>

      <Modal
        open={Boolean(approvalRun)}
        title="Approve the agent's prepared application?"
        onClose={() => {
          setApprovalRun(null);
          setApprovalDetail(null);
        }}
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setApprovalRun(null);
                setApprovalDetail(null);
              }}
              disabled={busy === "approve"}
            >
              Cancel
            </Button>
            <Button variant="primary" onClick={approveAndResume} disabled={busy === "approve"}>
              {busy === "approve" ? "Submitting…" : "Approve & resume"}
            </Button>
          </>
        }
      >
        {approvalDetail ? (
          <div className="space-y-3">
            <p className="text-sm text-muted">
              This issues a one-time approval token for this application only, then resumes the agent. The agent will
              submit and stop at tracking.
            </p>
            <div className="rounded border border-line bg-ink px-3 py-2">
              <p className="text-sm text-paper">
                {approvalDetail.job.title} — {approvalDetail.job.company}
              </p>
              <p className="mt-1 text-xs text-muted">Current status: {approvalDetail.status}</p>
            </div>
            <div className="max-h-56 space-y-1 overflow-auto text-xs">
              {approvalDetail.answers.map((answer) => (
                <div key={answer.id} className="flex gap-2 border-b border-line py-1 last:border-0">
                  <span className="w-36 shrink-0 text-muted">{answer.field_label ?? answer.field_name}</span>
                  <span className="break-words text-paper">{answer.field_value || "—"}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-danger">
              Only approve if every answer is accurate. CAPTCHA, login and MFA are never bypassed.
            </p>
          </div>
        ) : (
          <Spinner label="Loading the prepared form…" />
        )}
      </Modal>
    </div>
  );
}
