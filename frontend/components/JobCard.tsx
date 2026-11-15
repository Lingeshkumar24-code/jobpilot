"use client";

import { ExternalLink, MapPin, Sparkles } from "lucide-react";
import type { Job } from "@/lib/api";
import { Button, Score, timeAgo } from "@/components/ui";

function money(value: number | null, currency: string | null) {
  if (value === null) return null;
  const symbol = currency === "INR" ? "₹" : currency === "USD" ? "$" : "";
  return `${symbol}${Math.round(value).toLocaleString()}`;
}

export function JobCard({
  job,
  onApply,
  onDismiss,
  applying = false,
}: {
  job: Job;
  onApply?: () => void;
  onDismiss?: () => void;
  applying?: boolean;
}) {
  const salary =
    job.salary_min !== null || job.salary_max !== null
      ? `${money(job.salary_min, job.salary_currency) ?? "?"} – ${money(job.salary_max, job.salary_currency) ?? "?"}`
      : null;
  const explanation = job.match_explanation;

  return (
    <article className="rounded-lg border border-line bg-panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-paper">{job.title}</h3>
          <p className="mt-0.5 text-xs text-muted">
            {job.company}
            {job.location ? (
              <>
                {" · "}
                <MapPin size={11} className="mb-0.5 inline" /> {job.location}
              </>
            ) : null}
            {job.work_mode ? ` · ${job.work_mode}` : ""}
            {job.employment_type ? ` · ${job.employment_type.replaceAll("_", " ")}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Score value={job.match_score} />
          <a
            href={job.application_url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-muted hover:text-paper"
            aria-label="Open original listing"
          >
            <ExternalLink size={15} />
          </a>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {job.skills.slice(0, 8).map((skill) => (
          <span key={skill} className="rounded border border-line px-2 py-0.5 text-[11px] text-muted">
            {skill}
          </span>
        ))}
        {salary ? <span className="rounded border border-line px-2 py-0.5 text-[11px] text-muted">{salary}</span> : null}
        {job.source_display_name ? (
          <span className="rounded border border-line px-2 py-0.5 text-[11px] text-muted">
            via {job.source_display_name}
          </span>
        ) : null}
      </div>

      {job.description ? (
        <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-muted">{job.description}</p>
      ) : null}

      {explanation ? (
        <details className="mt-3 rounded-md border border-line bg-ink/40 px-3 py-2">
          <summary className="cursor-pointer text-xs text-muted">
            <Sparkles size={12} className="mb-0.5 inline" /> Why this score? {explanation.summary}
          </summary>
          <div className="mt-2 space-y-1 text-xs text-muted">
            {explanation.strengths.map((reason) => (
              <p key={reason}>• {reason}</p>
            ))}
            {explanation.missing_skills.length ? (
              <p className="text-amber">Missing from your profile: {explanation.missing_skills.join(", ")}</p>
            ) : null}
            <p className="pt-1 font-mono text-[10px] text-muted/70">
              engine {explanation.engine} · {timeAgo(explanation.scored_at)} · weights{" "}
              {Object.entries(explanation.weights_used)
                .map(([key, value]) => `${key} ${value}`)
                .join(", ")}
            </p>
          </div>
        </details>
      ) : null}

      {(onApply || onDismiss) && (
        <div className="mt-3 flex gap-2">
          {onApply ? (
            <Button size="sm" variant="primary" onClick={onApply} disabled={applying}>
              {applying ? "Opening & filling…" : "Open & fill application"}
            </Button>
          ) : null}
          {onDismiss ? (
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              Not interested
            </Button>
          ) : null}
        </div>
      )}
    </article>
  );
}
