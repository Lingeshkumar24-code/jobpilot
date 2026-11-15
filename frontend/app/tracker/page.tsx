"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatPanel } from "@/components/StatPanel";
import {
  Button,
  Card,
  Empty,
  Input,
  Notice,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  formatDate,
} from "@/components/ui";
import { api, ApiError, type Application } from "@/lib/api";

const FILTERS = [
  "ALL",
  "NEEDS_USER_INPUT",
  "VERIFICATION_PENDING",
  "USER_APPROVAL_PENDING",
  "APPROVED",
  "SUBMITTED",
  "CONFIRMED",
  "UNKNOWN_SUBMISSION_STATUS",
  "FAILED",
  "CANCELLED",
];

export default function TrackerPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState("ALL");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    const result = await api.listApplications({
      limit: 200,
      status: filter === "ALL" ? undefined : filter,
      q: query.trim() || undefined,
    });
    setApplications(result.applications);
    setCounts(result.counts);
  }

  useEffect(() => {
    load()
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to see your tracker."
            : err instanceof Error
              ? err.message
              : "Could not load the tracker",
        ),
      )
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function recordOutcome(application: Application, outcome: string) {
    if (!outcome) return;
    setBusy(application.id);
    setError(null);
    setNotice(null);
    try {
      await api.recordOutcome(application.id, outcome);
      await load();
      setNotice(`Recorded “${outcome}” for ${application.job.title}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the outcome");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="Application Tracker"
        description="Real statuses only. “Confirmed” means the target site showed confirmation; an unknown outcome stays unknown until you verify it."
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <StatPanel
          title="Pipeline"
          accent="amber"
          rows={[
            { label: "Awaiting approval", value: (counts.USER_APPROVAL_PENDING ?? 0) + (counts.APPROVED ?? 0) },
            { label: "Needs your input", value: (counts.NEEDS_USER_INPUT ?? 0) + (counts.CAPTCHA_REQUIRED ?? 0) + (counts.LOGIN_REQUIRED ?? 0) },
            { label: "Confirmed", value: counts.CONFIRMED ?? 0 },
          ]}
        />
        <StatPanel
          title="Outcomes"
          accent="signal"
          rows={[
            { label: "Unknown submission", value: counts.UNKNOWN_SUBMISSION_STATUS ?? 0 },
            { label: "Failed", value: counts.FAILED ?? 0 },
            { label: "Cancelled", value: counts.CANCELLED ?? 0 },
          ]}
        />
      </div>

      <Card>
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            setLoading(true);
            load()
              .catch((err) => setError(err instanceof Error ? err.message : "Could not load the tracker"))
              .finally(() => setLoading(false));
          }}
        >
          <Select value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Status filter">
            {FILTERS.map((status) => (
              <option key={status} value={status}>
                {status === "ALL" ? "All statuses" : status.replaceAll("_", " ").toLowerCase()}
              </option>
            ))}
          </Select>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Title or company"
            aria-label="Search applications"
          />
          <Button type="submit" disabled={loading}>
            Filter
          </Button>
        </form>
      </Card>

      {loading ? <Spinner label="Loading applications…" /> : null}

      {!loading && !applications.length ? (
        <Empty title="Nothing here yet">Applications appear as soon as you prepare one from a job.</Empty>
      ) : null}

      {applications.length ? (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="py-2 pr-3 font-medium">Role</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Submitted</th>
                  <th className="py-2 pr-3 font-medium">Outcome</th>
                  <th className="py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {applications.map((application) => (
                  <tr key={application.id} className="align-top">
                    <td className="py-3 pr-3">
                      <p className="text-paper">{application.job.title}</p>
                      <p className="text-xs text-muted">{application.job.company}</p>
                    </td>
                    <td className="py-3 pr-3">
                      <StatusBadge status={application.status} />
                    </td>
                    <td className="py-3 pr-3 text-xs text-muted">{formatDate(application.submitted_at)}</td>
                    <td className="py-3 pr-3">
                      <Select
                        value={application.outcome ?? ""}
                        disabled={busy === application.id}
                        onChange={(event) => recordOutcome(application, event.target.value)}
                        aria-label="Outcome"
                      >
                        <option value="">—</option>
                        <option value="interview">Interview</option>
                        <option value="offer">Offer</option>
                        <option value="rejected">Rejected</option>
                        <option value="withdrawn">Withdrawn</option>
                        <option value="no_response">No response</option>
                      </Select>
                    </td>
                    <td className="py-3">
                      <Link href={`/assistant?application=${application.id}`}>
                        <Button size="sm" variant="ghost">
                          Open
                        </Button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

