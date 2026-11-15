"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { JobCard } from "@/components/JobCard";
import { LiveBrowser } from "@/components/live-browser";
import { Button, Card, Empty, Input, Notice, PageHeader, Spinner, timeAgo } from "@/components/ui";
import {
  api,
  ApiError,
  type Job,
  type SourceResult,
  type StructuredFilters,
} from "@/lib/api";

type History = {
  id: string;
  raw_text: string;
  structured_filters: StructuredFilters | null;
  result_count: number;
  is_saved: boolean;
  last_run_at: string | null;
  created_at: string;
};

function FilterChips({ filters }: { filters: StructuredFilters }) {
  const chips: string[] = [];
  if (filters.role.length) chips.push(`Role: ${filters.role.join(", ")}`);
  if (filters.location.length) chips.push(`Location: ${filters.location.join(", ")}`);
  if (filters.work_mode.length) chips.push(`Mode: ${filters.work_mode.join(", ")}`);
  if (filters.employment_type.length) chips.push(`Type: ${filters.employment_type.join(", ")}`);
  if (filters.minimum_salary !== null) chips.push(`Min salary: ${filters.minimum_salary}`);
  if (filters.maximum_experience_years !== null) chips.push(`Max experience: ${filters.maximum_experience_years} yrs`);
  if (filters.posted_within_days !== null) chips.push(`Posted within ${filters.posted_within_days} days`);
  if (filters.internship_with_ppo) chips.push("Internship with PPO");
  if (filters.skills.length) chips.push(`Skills: ${filters.skills.join(", ")}`);
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <span key={chip} className="rounded border border-line bg-ink px-2 py-0.5 text-[11px] text-muted">
          {chip}
        </span>
      ))}
      {!chips.length ? <span className="text-xs text-muted">No hard filters — broad search.</span> : null}
    </div>
  );
}

export default function SearchPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<StructuredFilters | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sources, setSources] = useState<SourceResult[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [history, setHistory] = useState<History[]>([]);
  const [queryId, setQueryId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [interpreted, setInterpreted] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [browserSession, setBrowserSession] = useState<{ session_id: string; provider: "google" | "linkedin" | "indeed"; query: string; url: string; ticket: string } | null>(null);
  const [browserOpening, setBrowserOpening] = useState<string | null>(null);
  const [browserDriving, setBrowserDriving] = useState(false);
  const [allowBrowserVision, setAllowBrowserVision] = useState(false);
  const [browserActionResult, setBrowserActionResult] = useState<{ outcome: string; steps: { action: string; target: string; reason: string }[]; screenshot?: string | null } | null>(null);

  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("q");
    if (initial) setQuery(initial);
    api
      .searchHistory()
      .then(setHistory)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) setError("Sign in to search jobs.");
      });
  }, []);

  async function interpret() {
    if (query.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.searchIntent(query);
      setFilters(result.filters);
      setProvider(result.provider);
      setMissing(result.missing);
      setInterpreted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not interpret the query");
    } finally {
      setBusy(false);
    }
  }

  async function runSearch() {
    if (query.trim().length < 3) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.search(query, { limit: 25 });
      setFilters(result.filters);
      setProvider(result.provider);
      setJobs(result.jobs);
      setSources(result.sources);
      setWarnings(result.warnings);
      setQueryId(result.query_id);
      setInterpreted(true);
      setNotice(`Found ${result.total} matching job${result.total === 1 ? "" : "s"}.`);
      setHistory(await api.searchHistory());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  async function openProviderBrowser(target: "google" | "linkedin" | "indeed") {
    if (query.trim().length < 3) return;
    setBrowserOpening(target);
    setError(null);
    try {
      const session = await api.openBrowserSearch(target, query.trim());
      setBrowserSession({ session_id: session.session_id, provider: target, query: session.query, url: session.url, ticket: session.ticket });
      setAllowBrowserVision(false);
      setBrowserActionResult(null);
      setNotice(`Opened ${target === "google" ? "Google" : target === "linkedin" ? "LinkedIn" : "Indeed"} for “${session.query}”. Sign in in the browser if it asks.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the browser search");
    } finally {
      setBrowserOpening(null);
    }
  }

  async function letAgentDriveBrowser() {
    if (!browserSession) return;
    setBrowserDriving(true);
    setError(null);
    try {
      const result = await api.driveBrowserSearch(browserSession.ticket, allowBrowserVision);
      setBrowserActionResult({
        outcome: result.outcome,
        steps: result.steps,
        screenshot: result.screenshot?.base64 ? `data:${result.screenshot.mime};base64,${result.screenshot.base64}` : null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The visual browser agent could not continue");
    } finally {
      setBrowserDriving(false);
    }
  }

  async function prepare(job: Job) {
    setApplying(job.id);
    setError(null);
    try {
      const result = await api.openAndFillApplication(job.id);
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
        setError(err instanceof Error ? err.message : "Could not open the application");
    } finally {
      setApplying(null);
    }
  }

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="AI Job Search"
        description="Describe what you want in plain language. The parser extracts roles, cities, salary, experience and freshness; a missing requirement is reported rather than guessed."
      />

      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            runSearch();
          }}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. remote GenAI internships with PPO, 6 LPA+, posted this week"
            aria-label="Job search query"
          />
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={interpret} disabled={busy || query.trim().length < 3}>
              Interpret
            </Button>
            <Button type="submit" variant="primary" disabled={busy || query.trim().length < 3}>
              {busy ? "Searching…" : "Search"}
            </Button>
          </div>
        </form>

        {filters ? (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <FilterChips filters={filters} />
              <span className="font-mono text-[10px] text-muted">
                parsed by {provider ?? "—"}
                {missing.length ? ` · missing: ${missing.join(", ")}` : ""}
              </span>
            </div>
            {filters.notes.length ? (
              <p className="text-xs text-muted">{filters.notes.join(" ")}</p>
            ) : null}
            {interpreted && queryId ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  const name = window.prompt("Name this search");
                  if (!name) return;
                  await api.saveSearch(queryId, name);
                  setHistory(await api.searchHistory());
                  setNotice("Search saved.");
                }}
              >
                Save this search
              </Button>
            ) : null}
          </div>
        ) : null}
      </Card>

      <Card title="Search directly in a browser">
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="ghost" disabled={query.trim().length < 3 || !!browserOpening} onClick={() => openProviderBrowser("google")}>
            {browserOpening === "google" ? "Opening…" : "Open Google"}
          </Button>
          <Button type="button" variant="ghost" disabled={query.trim().length < 3 || !!browserOpening} onClick={() => openProviderBrowser("linkedin")}>
            {browserOpening === "linkedin" ? "Opening…" : "Open LinkedIn"}
          </Button>
          <Button type="button" variant="ghost" disabled={query.trim().length < 3 || !!browserOpening} onClick={() => openProviderBrowser("indeed")}>
            {browserOpening === "indeed" ? "Opening…" : "Open Indeed"}
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted">For example, enter “AI jobs in Bengaluru” above. This opens a user controlled browser session; provider sign in and any security check stay with you.</p>
      </Card>

      {browserSession ? (
        <>
          <Card title="Visual browser agent">
            <p className="mb-3 text-xs text-muted">Nemotron can use visible mouse clicks to open a relevant job and reach its application form. It stops at sign-in, CAPTCHA, personal data, or the final submit step.</p>
            <label className="mb-3 flex items-start gap-2 text-xs text-muted">
              <input type="checkbox" checked={allowBrowserVision} onChange={(event) => setAllowBrowserVision(event.target.checked)} />
              Send screenshots of this browser page, which may show account details, to OpenRouter/Nemotron for visual guidance.
            </label>
            <Button type="button" variant="primary" disabled={browserDriving || !allowBrowserVision} onClick={letAgentDriveBrowser}>
              {browserDriving ? "Agent using the browser…" : "Let AI use the mouse"}
            </Button>
            {browserActionResult ? (
              <div className="mt-3 space-y-1 text-xs text-muted" aria-live="polite">
                <p className="text-paper">{browserActionResult.outcome}</p>
                {browserActionResult.steps.map((step, index) => (
                  <p key={`${step.action}-${index}`}>{index + 1}. {step.action}: {step.target || step.reason}</p>
                ))}
              </div>
            ) : null}
          </Card>
          <LiveBrowser url={api.browserSearchStreamUrl(browserSession.ticket)} label={`${browserSession.provider} · ${browserSession.query}`} snapshot={browserActionResult?.screenshot} />
        </>
      ) : null}

      {error ? <Notice>{error}</Notice> : null}
      {notice && !warnings.length ? <Notice tone="success">{notice}</Notice> : null}

      {sources.length ? (
        <Card title="Sources">
          <div className="grid gap-2 sm:grid-cols-2">
            {sources.map((source) => (
              <div key={source.key} className="flex items-start justify-between gap-2 rounded border border-line px-3 py-2">
                <div>
                  <p className="text-xs text-paper">{source.display_name}</p>
                  <p className="text-[11px] text-muted">
                    {source.status} · {source.count} listing(s) · {source.duration_ms} ms
                    {source.message ? ` · ${source.message}` : ""}
                  </p>
                </div>
                <span
                  className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                    source.status === "ok" ? "bg-signal" : source.status === "error" ? "bg-danger" : "bg-muted"
                  }`}
                  aria-label={source.status}
                />
              </div>
            ))}
          </div>
          {warnings.length ? (
            <div className="mt-3 space-y-1 text-xs text-amber">
              {warnings.map((warning) => (
                <p key={warning}>• {warning}</p>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-sm text-muted">
          Results {jobs.length ? <span className="text-paper">({jobs.length})</span> : null}
        </h2>
        {busy && !jobs.length ? <Spinner label="Contacting sources…" /> : null}
        {!busy && !jobs.length ? (
          <Empty title="No results yet">
            Run a search. Listings only appear when a configured source actually returned them; nothing is fabricated.
          </Empty>
        ) : null}
        {jobs.map((job) => (
          <JobCard key={job.id} job={job} onApply={() => prepare(job)} applying={applying === job.id} />
        ))}
      </section>

      {history.length ? (
        <Card title="Recent searches">
          <ul className="divide-y divide-line">
            {history.slice(0, 8).map((item) => (
              <li key={item.id} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
                <button
                  onClick={() => setQuery(item.raw_text)}
                  className="min-w-0 flex-1 truncate text-left text-sm text-paper hover:text-amber"
                >
                  {item.raw_text}
                  {item.is_saved ? <span className="ml-2 text-[10px] text-signal">saved</span> : null}
                </button>
                <span className="shrink-0 text-xs text-muted">
                  {item.result_count} · {timeAgo(item.last_run_at ?? item.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
