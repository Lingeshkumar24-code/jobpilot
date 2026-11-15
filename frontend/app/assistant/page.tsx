"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
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
  Textarea,
  formatDate,
} from "@/components/ui";
import {
  api,
  ApiError,
  type Answer,
  type Application,
  type ApplicationDetail,
} from "@/lib/api";

const EDITABLE = new Set(["FORM_FILLED", "VERIFICATION_PENDING", "USER_APPROVAL_PENDING", "NEEDS_USER_INPUT"]);
const CAN_ANALYZE = new Set(["DISCOVERED", "MATCHED", "APPLICATION_OPENED", "NEEDS_USER_INPUT", "FORM_ANALYZED"]);
const CAN_FILL = new Set(["FORM_ANALYZED", "NEEDS_USER_INPUT"]);
const CAN_REQUEST = new Set(["VERIFICATION_PENDING"]);

type ApprovalRequest = {
  application_id: string;
  approval_token: string;
  expires_at: string;
  summary: {
    job?: { title?: string; company?: string; url?: string };
    resume?: { filename?: string; version?: number } | null;
    answers?: { label?: string | null; value?: string | null }[];
    warnings?: string[];
  };
};

export default function AssistantPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});
  const [approval, setApproval] = useState<ApprovalRequest | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [manualEvidence, setManualEvidence] = useState("");
  const [screenshot, setScreenshot] = useState<string | null>(null);

  async function loadList(preferred?: string) {
    const result = await api.listApplications({ limit: 100 });
    setApplications(result.applications);
    const chosen =
      preferred ??
      selectedId ??
      new URLSearchParams(window.location.search).get("application") ??
      result.applications.find((item) => item.status === "USER_APPROVAL_PENDING")?.id ??
      result.applications[0]?.id ??
      null;
    setSelectedId(chosen);
    return chosen;
  }

  async function loadDetail(id: string) {
    const data = await api.getApplication(id);
    setDetail(data);
    setAnswerDrafts(
      Object.fromEntries(data.answers.map((answer) => [answer.id, answer.field_value ?? ""])),
    );
    return data;
  }

  useEffect(() => {
    (async () => {
      try {
        const searchNotice = new URLSearchParams(window.location.search).get("notice");
        if (searchNotice) setNotice(searchNotice);
        const chosen = await loadList();
        if (chosen) await loadDetail(chosen);
      } catch (err) {
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to use the application assistant."
            : err instanceof Error
              ? err.message
              : "Could not load applications",
        );
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!detail) return;
    setScreenshot(null);
    if (detail.screenshot_available) {
      api
        .applicationScreenshot(detail.id)
        .then((blob) => setScreenshot(URL.createObjectURL(blob)))
        .catch(() => undefined);
    }
  }, [detail?.id, detail?.screenshot_available]);

  async function choose(id: string) {
    setSelectedId(id);
    setError(null);
    setNotice(null);
    setLoading(true);
    try {
      await loadDetail(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load application");
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    if (!selectedId) return;
    await Promise.all([loadList(selectedId), loadDetail(selectedId)]);
  }

  async function runAction(label: string, action: () => Promise<unknown>, success?: string) {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      await action();
      await refresh();
      if (success) setNotice(success);
    } catch (err) {
      if (err instanceof ApiError) {
        const detailValue = err.detail as { missing_required?: string[]; message?: string } | undefined;
        const missing = detailValue?.missing_required?.length
          ? ` Missing: ${detailValue.missing_required.join(", ")}.`
          : "";
        setError(`${err.message}${missing}`);
      } else {
        setError(err instanceof Error ? err.message : "Action failed");
      }
      await refresh().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  }

  async function requestApproval() {
    if (!detail) return;
    setBusy("request");
    setError(null);
    setNotice(null);
    try {
      const result = await api.requestApproval(detail.id);
      setApproval(result);
      await loadDetail(detail.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not request approval");
    } finally {
      setBusy(null);
    }
  }

  async function confirmApproval() {
    if (!detail || !approval) return;
    setBusy("approve");
    setError(null);
    try {
      const approved = await api.approve(detail.id, approval.approval_token);
      setApproval(null);
      const result = await api.submit(detail.id, approved.proof);
      await refresh();
      if (result.outcome === "CONFIRMED") {
        setNotice("Submitted and confirmed by the target site.");
      } else if (result.outcome === "UNKNOWN_SUBMISSION_STATUS") {
        setError(
          "The worker could not observe a confirmation. Status is UNKNOWN — verify on the employer site before marking it confirmed.",
        );
      } else {
        setError(`The target site did not confirm the submission (${result.outcome ?? "no outcome"}).`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
      await refresh().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  }

  async function saveAnswer(answer: Answer) {
    if (!detail) return;
    setBusy(answer.id);
    setError(null);
    try {
      await api.updateAnswer(detail.id, answer.id, answerDrafts[answer.id] ?? "");
      await loadDetail(detail.id);
      setNotice("Answer saved. Re-run the form check to verify it.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save answer");
    } finally {
      setBusy(null);
    }
  }

  const pending = useMemo(
    () =>
      applications.filter((item) =>
        ["USER_APPROVAL_PENDING", "APPROVED", "VERIFICATION_PENDING", "NEEDS_USER_INPUT"].includes(item.status),
      ).length,
    [applications],
  );

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="Application Assistant"
        description="Prepare the form, review every answer, then approve this one application. Nothing is submitted until you press Approve, and approval expires."
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}

      {loading && !applications.length ? <Spinner label="Loading applications…" /> : null}

      {!loading && !applications.length ? (
        <Empty title="No applications prepared yet">
          Find a job you like and choose “Prepare application”. Nothing is sent automatically.
          <div className="mt-3 flex justify-center">
            <Link href="/search">
              <Button size="sm" variant="primary">
                Search jobs
              </Button>
            </Link>
          </div>
        </Empty>
      ) : null}

      {applications.length ? (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card title={`Applications (${pending} need you)`}>
            <ul className="max-h-[560px] space-y-1 overflow-auto">
              {applications.map((item) => (
                <li key={item.id}>
                  <button
                    onClick={() => choose(item.id)}
                    className={`w-full rounded-md px-2.5 py-2 text-left transition-colors ${
                      selectedId === item.id ? "bg-panel-raised" : "hover:bg-panel-raised"
                    }`}
                  >
                    <span className="block truncate text-sm text-paper">{item.job.title}</span>
                    <span className="block truncate text-[11px] text-muted">
                      {item.job.company} · {item.status.replaceAll("_", " ").toLowerCase()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          {detail ? (
            <div className="space-y-4">
              <Card
                title={detail.job.title}
                action={<StatusBadge status={detail.status} />}
              >
                <p className="text-xs text-muted">
                  {detail.job.company}
                  {detail.job.location ? ` · ${detail.job.location}` : ""} ·{" "}
                  <a
                    href={detail.job.application_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-amber hover:underline"
                  >
                    original listing
                  </a>
                </p>

                {detail.failure_reason ? (
                  <div className="mt-3">
                    <Notice>{detail.failure_reason}</Notice>
                  </div>
                ) : null}

                {detail.status === "CAPTCHA_REQUIRED" || detail.status === "LOGIN_REQUIRED" ? (
                  <div className="mt-3">
                    <Notice tone="info">
                      This site asked for a CAPTCHA/login. That is not bypassed automatically. Apply manually on the
                      original listing, then record the outcome in the tracker.
                    </Notice>
                  </div>
                ) : null}

                <div className="mt-4 flex flex-wrap gap-2">
                  {CAN_ANALYZE.has(detail.status) ? (
                    <Button
                      size="sm"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        runAction("analyze", () => api.analyzeApplication(detail.id), "Form inspected.")
                      }
                    >
                      {busy === "analyze" ? "Inspecting…" : "Inspect form"}
                    </Button>
                  ) : null}
                  {CAN_FILL.has(detail.status) ? (
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        runAction("fill", () => api.fillApplication(detail.id), "Form values prepared.")
                      }
                    >
                      {busy === "fill" ? "Preparing…" : "Fill & verify"}
                    </Button>
                  ) : null}
                  {CAN_REQUEST.has(detail.status) ? (
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={Boolean(busy)}
                      onClick={requestApproval}
                    >
                      {busy === "request" ? "Preparing approval…" : "Review & approve"}
                    </Button>
                  ) : null}
                  {detail.status === "APPROVED" ? (
                    <Notice tone="info">
                      Approved but not submitted. For safety the one-time proof is issued only in the approval step;
                      reject and repeat if you navigated away.
                    </Notice>
                  ) : null}
                  {!["CONFIRMED", "SUBMITTED", "CANCELLED", "REJECTED"].includes(detail.status) ? (
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={Boolean(busy)}
                      onClick={() => {
                        if (!window.confirm("Reject this application? Nothing will be submitted.")) return;
                        runAction("reject", () => api.reject(detail.id, "Rejected by the user in the assistant."), "Application rejected.");
                      }}
                    >
                      Reject
                    </Button>
                  ) : null}
                </div>
              </Card>

              {detail.preview?.verification ? (
                <Card title="Form check">
                  {(() => {
                    const verification = detail.preview?.verification as
                      | { ok?: boolean; missing_required?: string[]; notes?: string[] }
                      | undefined;
                    return (
                      <div className="space-y-2 text-sm">
                        <p className={verification?.ok ? "text-signal" : "text-danger"}>
                          {verification?.ok
                            ? "All required values are present."
                            : `Still required: ${(verification?.missing_required ?? []).join(", ") || "unknown"}`}
                        </p>
                        {(verification?.notes ?? []).map((note) => (
                          <p key={note} className="text-xs text-muted">
                            • {note}
                          </p>
                        ))}
                        {!verification?.ok && CAN_FILL.has(detail.status) ? (
                          <p className="text-xs text-muted">
                            Edit the answers below, save them, then choose “Fill & verify” again.
                          </p>
                        ) : null}
                      </div>
                    );
                  })()}
                </Card>
              ) : null}

              <Card title="Answers to be submitted">
                {detail.answers.length ? (
                  <ul className="divide-y divide-line">
                    {detail.answers.map((answer) => (
                      <li key={answer.id} className="space-y-1 py-3 first:pt-0 last:pb-0">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-xs text-paper">
                            {answer.field_label ?? answer.field_name}
                            {answer.is_required ? <span className="ml-1 text-danger">*</span> : null}
                          </span>
                          <span className="font-mono text-[10px] uppercase text-muted">
                            {answer.source}
                            {answer.is_user_edited ? " · edited" : ""}
                          </span>
                        </div>
                        {EDITABLE.has(detail.status) ? (
                          <div className="flex gap-2">
                            <Input
                              value={answerDrafts[answer.id] ?? ""}
                              onChange={(event) =>
                                setAnswerDrafts((current) => ({ ...current, [answer.id]: event.target.value }))
                              }
                              placeholder={answer.field_type === "checkbox" ? "true / false" : ""}
                            />
                            <Button
                              size="sm"
                              disabled={busy === answer.id || (answerDrafts[answer.id] ?? "") === (answer.field_value ?? "")}
                              onClick={() => saveAnswer(answer)}
                            >
                              Save
                            </Button>
                          </div>
                        ) : (
                          <p className="break-words text-sm text-paper">{answer.field_value || "—"}</p>
                        )}
                        {answer.validation_error ? (
                          <p className="text-xs text-danger">{answer.validation_error}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted">Inspect the form first. Answers are generated from your profile.</p>
                )}
              </Card>

              {detail.status === "UNKNOWN_SUBMISSION_STATUS" ? (
                <Card title="Could not confirm the outcome">
                  <p className="text-sm text-muted">
                    The worker clicked submit but did not observe confirmation text or a success URL. Check the employer
                    site. If it shows your application, record the evidence here.
                  </p>
                  <div className="mt-3 space-y-2">
                    <Textarea
                      value={manualEvidence}
                      onChange={(event) => setManualEvidence(event.target.value)}
                      placeholder="What did the employer site show? e.g. “Application status: Received” on the dashboard."
                    />
                    <Button
                      size="sm"
                      disabled={manualEvidence.trim().length < 5 || Boolean(busy)}
                      onClick={() =>
                        runAction(
                          "manual",
                          () => api.confirmManual(detail.id, manualEvidence.trim()),
                          "Marked confirmed from your evidence.",
                        )
                      }
                    >
                      Record manual confirmation
                    </Button>
                  </div>
                </Card>
              ) : null}

              {detail.confirmation_evidence ? (
                <Card title="Confirmation evidence">
                  <pre className="overflow-auto whitespace-pre-wrap text-xs text-muted">
                    {JSON.stringify(detail.confirmation_evidence, null, 2)}
                  </pre>
                </Card>
              ) : null}

              {screenshot ? (
                <Card title="Last screenshot">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={screenshot} alt="Application page screenshot" className="w-full rounded border border-line" />
                </Card>
              ) : null}

              <Card title="Timeline">
                {detail.events.length ? (
                  <ol className="space-y-2">
                    {detail.events.map((event) => (
                      <li key={event.id} className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                        <span className="text-paper">
                          {event.event_type.replaceAll("_", " ")}
                          {event.to_status ? ` → ${event.to_status.replaceAll("_", " ")}` : ""}
                        </span>
                        <span className="text-muted">
                          {event.actor} · {formatDate(event.created_at)}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-sm text-muted">No events yet.</p>
                )}
              </Card>
            </div>
          ) : null}
        </div>
      ) : null}

      <Modal
        open={Boolean(approval)}
        title="Approve this application?"
        onClose={() => setApproval(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setApproval(null)} disabled={busy === "approve"}>
              Cancel
            </Button>
            <Button variant="primary" onClick={confirmApproval} disabled={busy === "approve"}>
              {busy === "approve" ? "Submitting…" : "Approve & submit"}
            </Button>
          </>
        }
      >
        {approval ? (
          <div className="space-y-3">
            <p className="text-sm text-muted">
              You are approving exactly one submission. The approval expires at{" "}
              <span className="text-paper">{formatDate(approval.expires_at)}</span> and its token is shown only once.
            </p>
            <div className="rounded border border-line bg-ink px-3 py-2 text-sm">
              <p className="text-paper">
                {approval.summary.job?.title} — {approval.summary.job?.company}
              </p>
              <p className="mt-1 text-xs text-muted">
                Resume: {approval.summary.resume?.filename ?? "selected resume"} ·{" "}
                {approval.summary.answers?.length ?? 0} answer(s)
              </p>
            </div>
            <div className="max-h-56 space-y-1 overflow-auto text-xs">
              {(approval.summary.answers ?? []).map((item, index) => (
                <div key={`${item.label}-${index}`} className="flex gap-2 border-b border-line py-1 last:border-0">
                  <span className="w-36 shrink-0 text-muted">{item.label ?? "Field"}</span>
                  <span className="break-words text-paper">{item.value || "—"}</span>
                </div>
              ))}
            </div>
            {(approval.summary.warnings ?? []).length ? (
              <Notice>{approval.summary.warnings?.join(" ")}</Notice>
            ) : null}
            <p className="text-xs text-danger">
              Do not approve unless the answers above are accurate. The worker will not bypass CAPTCHA, login or MFA.
            </p>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
