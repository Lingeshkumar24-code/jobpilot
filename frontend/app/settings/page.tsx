"use client";

import { useEffect, useState } from "react";
import { Button, Card, Input, Notice, PageHeader, Spinner, formatDate } from "@/components/ui";
import { api, ApiError, type Preferences } from "@/lib/api";

type AuditEntry = {
  id: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
};

export default function SettingsPage() {
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [boards, setBoards] = useState("");
  const [sites, setSites] = useState("");
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getPreferences(), api.auditTrail(50)])
      .then(([prefs, entries]) => {
        setPreferences(prefs);
        setBoards((prefs.greenhouse_boards ?? []).join(", "));
        setSites((prefs.lever_sites ?? []).join(", "));
        setAudit(entries);
      })
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to manage settings."
            : err instanceof Error
              ? err.message
              : "Could not load settings",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  async function save() {
    if (!preferences) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.updatePreferences({
        ...preferences,
        greenhouse_boards: boards
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        lever_sites: sites
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      });
      setPreferences(updated);
      setNotice("Preferences saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save preferences");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Settings"
        description="Notification and source preferences, plus a personal audit trail of every approval, submission and outcome."
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}
      {loading ? <Spinner label="Loading settings…" /> : null}

      {preferences ? (
        <Card title="Preferences">
          <div className="space-y-4">
            <label className="flex items-center gap-2 text-sm text-paper">
              <input
                type="checkbox"
                checked={preferences.digest_enabled}
                onChange={(event) =>
                  setPreferences({ ...preferences, digest_enabled: event.target.checked })
                }
              />
              Daily email digest
            </label>
            <div>
              <label htmlFor="digest-time" className="text-xs text-muted">
                Digest time (UTC, HH:MM)
              </label>
              <Input
                id="digest-time"
                value={preferences.digest_time ?? ""}
                onChange={(event) => setPreferences({ ...preferences, digest_time: event.target.value })}
                placeholder="08:00"
                className="mt-1 max-w-[140px]"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-paper">
              <input
                type="checkbox"
                checked={preferences.email_notifications}
                onChange={(event) =>
                  setPreferences({ ...preferences, email_notifications: event.target.checked })
                }
              />
              Application status notifications
            </label>
            <div>
              <label htmlFor="boards" className="text-xs text-muted">
                Greenhouse boards (company slugs, comma separated)
              </label>
              <Input
                id="boards"
                value={boards}
                onChange={(event) => setBoards(event.target.value)}
                placeholder="stripe, figma"
                className="mt-1"
              />
            </div>
            <div>
              <label htmlFor="sites" className="text-xs text-muted">
                Lever sites (company slugs, comma separated)
              </label>
              <Input
                id="sites"
                value={sites}
                onChange={(event) => setSites(event.target.value)}
                placeholder="netflix, plaid"
                className="mt-1"
              />
            </div>
            <Button variant="primary" onClick={save} disabled={busy}>
              {busy ? "Saving…" : "Save preferences"}
            </Button>
          </div>
        </Card>
      ) : null}

      <Card title="Audit trail">
        {audit.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="py-2 pr-3 font-medium">Action</th>
                  <th className="py-2 pr-3 font-medium">Resource</th>
                  <th className="py-2 pr-3 font-medium">Details</th>
                  <th className="py-2 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {audit.map((entry) => (
                  <tr key={entry.id} className="align-top">
                    <td className="py-2 pr-3 font-mono text-xs text-paper">{entry.action}</td>
                    <td className="py-2 pr-3 text-xs text-muted">
                      {entry.resource_type ?? "—"}
                      <br />
                      <span className="font-mono">{entry.resource_id?.slice(0, 12) ?? ""}</span>
                    </td>
                    <td className="max-w-[280px] py-2 pr-3 text-xs text-muted">
                      {entry.details ? JSON.stringify(entry.details) : "—"}
                    </td>
                    <td className="py-2 text-xs text-muted">{formatDate(entry.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted">No audit events yet.</p>
        )}
      </Card>
    </div>
  );
}
