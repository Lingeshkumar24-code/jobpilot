"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { JobCard } from "@/components/JobCard";
import { StatPanel } from "@/components/StatPanel";
import { Button, Card, Empty, Input, Notice, PageHeader, Spinner } from "@/components/ui";
import { api, ApiError, type Match } from "@/lib/api";

type Stats = {
  total: number;
  dismissed: number;
  scored_today: number;
  average_score: number | null;
  above_threshold: number;
};

export default function MatchesPage() {
  const router = useRouter();
  const [matches, setMatches] = useState<Match[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [query, setQuery] = useState("");
  const [minScore, setMinScore] = useState("");
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const params: { q?: string; min_score?: number; limit: number } = { limit: 50 };
    if (query.trim()) params.q = query.trim();
    if (minScore) params.min_score = Number(minScore);
    const result = await api.listMatches(params);
    setMatches(result.matches);
  }

  useEffect(() => {
    Promise.all([load(), api.matchStats().then(setStats)])
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) setError("Sign in to see your ranked matches.");
        else setError(err instanceof Error ? err.message : "Could not load matches");
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="Matches"
        description="Ranked by a transparent score. Open any card to see the exact weights, matched skills and what is missing — no black-box ranking."
        action={
          <Link href="/search">
            <Button variant="primary">Find more jobs</Button>
          </Link>
        }
      />

      {error ? <Notice>{error}</Notice> : null}

      {stats ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <StatPanel
            title="Ranking"
            accent="signal"
            rows={[
              { label: "Scored matches", value: stats.total },
              { label: "Above threshold", value: stats.above_threshold },
              {
                label: "Average score",
                value: stats.average_score === null ? "—" : `${Math.round(stats.average_score)}%`,
              },
            ]}
          />
          <StatPanel
            title="Hygiene"
            accent="amber"
            rows={[
              { label: "Dismissed", value: stats.dismissed },
              { label: "Scored today", value: stats.scored_today },
              { label: "Shown now", value: matches.length },
            ]}
          />
        </div>
      ) : null}

      <Card>
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            setLoading(true);
            load()
              .catch((err) => setError(err instanceof Error ? err.message : "Could not load matches"))
              .finally(() => setLoading(false));
          }}
        >
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by title or company"
            aria-label="Filter matches"
          />
          <Input
            value={minScore}
            onChange={(event) => setMinScore(event.target.value.replace(/[^0-9]/g, ""))}
            placeholder="Min score"
            className="sm:w-32"
            aria-label="Minimum score"
          />
          <Button type="submit" disabled={loading}>
            Apply filters
          </Button>
        </form>
      </Card>

      {loading ? <Spinner label="Loading matches…" /> : null}

      <div className="space-y-3">
        {!loading && !matches.length ? (
          <Empty title="No ranked matches">
            Upload a resume and run a natural-language search. Matching uses only evidence from your profile and the
            listing.
          </Empty>
        ) : null}
        {matches.map((match) => (
          <JobCard
            key={match.id}
            job={match.job}
            applying={applying === match.id}
            onApply={async () => {
              setApplying(match.id);
              try {
                const result = await api.openAndFillApplication(match.job.id);
                const notice = result.notice ? `&notice=${encodeURIComponent(result.notice)}` : "";
                router.push(`/assistant?application=${result.id}${notice}`);
              } catch (err) {
                if (err instanceof ApiError) {
                  const detail = err.detail as { application_id?: string } | undefined;
                  if (err.status === 409 && detail?.application_id) {
                    router.push(`/assistant?application=${detail.application_id}`);
                    return;
                  }
                }
                setError(err instanceof Error ? err.message : "Could not prepare the application");
              } finally {
                setApplying(null);
              }
            }}
            onDismiss={async () => {
              try {
                await api.dismissMatch(match.id);
                setMatches((current) => current.filter((item) => item.id !== match.id));
                setStats(await api.matchStats());
              } catch (err) {
                setError(err instanceof Error ? err.message : "Could not dismiss match");
              }
            }}
          />
        ))}
      </div>
    </div>
  );
}

