type StatRow = { label: string; value: number | string };

export function StatPanel({
  title,
  accent,
  rows,
}: {
  title: string;
  accent?: "amber" | "signal";
  rows: StatRow[];
}) {
  return (
    <div className="rounded-lg border border-line bg-panel">
      <div
        className={`h-[2px] rounded-t-lg ${
          accent === "signal" ? "bg-signal" : accent === "amber" ? "bg-amber" : "bg-line"
        }`}
      />
      <div className="p-4">
        <h3 className="text-sm text-muted">{title}</h3>
        <dl className="mt-3 space-y-2">
          {rows.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between">
              <dt className="text-sm text-paper">{row.label}</dt>
              <dd className="font-mono text-sm text-paper">{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
