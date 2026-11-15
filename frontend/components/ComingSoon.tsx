export function ComingSoon({ phase, description }: { phase: string; description: string }) {
  return (
    <div className="flex min-h-[50vh] flex-col items-start justify-center gap-2 rounded-lg border border-dashed border-line px-6">
      <p className="font-mono text-xs text-muted">{phase}</p>
      <h2 className="font-display text-xl text-paper">Not built yet</h2>
      <p className="max-w-md text-sm text-muted">{description}</p>
    </div>
  );
}
