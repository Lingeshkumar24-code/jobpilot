"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { JobCard } from "@/components/JobCard";
import { StatPanel } from "@/components/StatPanel";
import { Button, Card, Empty, Notice, PageHeader, Spinner } from "@/components/ui";
import { api, ApiError, type ApplicationStats, type Match, type SystemStatus } from "@/lib/api";

export default function Overview() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [stats, setStats] = useState<ApplicationStats | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    Promise.all([api.systemStatus(), api.applicationStats(), api.listMatches({ limit: 5 })])
      .then(([system, applicationStats, matchList]) => {
        if (!active) return;
        setStatus(system);
        setStats(applicationStats);
        setMatches(matchList.matches);
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError && err.status === 401 ? "Sign in to see your live dashboard." : err.message);
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="Good to see you."
        description="Live counts from your database. Nothing is submitted without an explicit, per-application approval."
        action={
          <Link href="/search">
            <Button variant="primary">Search jobs</Button>
          </Link>
        }
      />

      {error ? <Notice>{error}</Notice> : null}
      {loading ? <Spinner label="Loading your dashboard…" /> : null}

      {status && stats ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <StatPanel
            title="Radar"
            accent="signal"
            rows={[
              { label: "Active jobs stored", value: status.counts.jobs ?? 0 },
              { label: "Your matches", value: status.counts.matches ?? 0 },
              { label: "Sources configured", value: status.sources.filter((source) => source.configured).length },
            ]}
          />
          <StatPanel
            title="Pipeline"
            accent="amber"
            rows={[
              { label: "Awaiting your approval", value: stats.pending_approval },
              { label: "Confirmed submissions", value: stats.confirmed },
              { label: "Needs more information", value: stats.needs_input },
            ]}
          />
        </div>
      ) : null}

      <Card title="Recommended today" action={<Link href="/matches" className="text-xs text-muted hover:text-paper">View all</Link>}>
        {matches.length ? (
          <div className="space-y-3">
            {matches.map((match) => (
              <JobCard key={match.id} job={match.job} />
            ))}
          </div>
        ) : (
          <Empty title="No matches yet">
            Upload a resume, then run a search. Matches are scored from what is actually in your profile — never guessed.
            <div className="mt-3 flex justify-center gap-2">
              <Link href="/resume">
                <Button size="sm">Upload resume</Button>
              </Link>
              <Link href="/search">
                <Button size="sm" variant="primary">Run a search</Button>
              </Link>
            </div>
          </Empty>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Safety status">
          <ul className="space-y-2 text-sm">
            <li className="flex justify-between">
              <span className="text-muted">Submission approval</span>
              <span className="text-signal">Always required</span>
            </li>
            <li className="flex justify-between">
              <span className="text-muted">Browser worker</span>
              <span className={status?.browser_worker_configured ? "text-paper" : "text-muted"}>
                {status?.browser_worker_configured ? "Configured" : "Not configured"}
              </span>
            </li>
            <li className="flex justify-between">
              <span className="text-muted">LLM provider</span>
              <span className="font-mono text-xs text-paper">{status?.llm_provider ?? "—"}</span>
            </li>
            <li className="flex justify-between">
              <span className="text-muted">Storage</span>
              <span className="font-mono text-xs text-paper">{status?.storage_backend ?? "—"}</span>
            </li>
          </ul>
        </Card>
        <Card title="What happens next">
          <p className="text-sm leading-relaxed text-muted">
            Search in natural language, review the explanation behind each score, then prepare a form. You see every
            answer before approving it. The worker only reports a submission as confirmed when the target site shows
            confirmation text or a success URL.
          </p>
          <div className="mt-3 flex gap-2">
            <Link href="/assistant">
              <Button size="sm">Open assistant</Button>
            </Link>
            <Link href="/tracker">
              <Button size="sm" variant="ghost">Tracker</Button>
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}

