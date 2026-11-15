export function JobRow({
  title,
  company,
  location,
  matchScore,
  postedDaysAgo,
}: {
  title: string;
  company: string;
  location: string;
  matchScore: number;
  postedDaysAgo: number;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line py-4 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-paper">
          {title} <span className="font-normal text-muted">· {company}</span>
        </p>
        <p className="mt-0.5 text-xs text-muted">
          {location} · posted {postedDaysAgo === 1 ? "yesterday" : `${postedDaysAgo} days ago`}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="font-mono text-sm text-signal">{matchScore}%</span>
        <button className="rounded-md border border-line px-3 py-1.5 text-xs text-paper hover:border-amber">
          Review
        </button>
      </div>
    </div>
  );
}
