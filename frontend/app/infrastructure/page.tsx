"use client";

import { useEffect, useState } from "react";
import { Card, Notice, PageHeader, Spinner, formatDate } from "@/components/ui";
import { api, ApiError, type SystemStatus } from "@/lib/api";

export default function InfrastructurePage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .systemStatus()
      .then(setStatus)
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to see infrastructure status."
            : err instanceof Error
              ? err.message
              : "Could not load status",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Infrastructure"
        description="Live configuration and counts from this deployment. This page reports what is actually connected — it does not provision cloud resources."
      />

      {error ? <Notice>{error}</Notice> : null}
      {loading ? <Spinner label="Checking services…" /> : null}

      {status ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              { label: "Environment", value: status.environment },
              { label: "Database", value: status.database },
              { label: "Storage", value: status.storage_backend },
              { label: "LLM provider", value: status.llm_provider },
              {
                label: "Browser worker",
                value: status.browser_worker_configured
                  ? status.browser_worker_reachable === false
                    ? "configured · unreachable"
                    : "configured · reachable"
                  : "not configured",
              },
              { label: "n8n", value: status.n8n_configured ? "configured" : "not configured" },
            ].map((item) => (
              <Card key={item.label}>
                <p className="text-xs text-muted">{item.label}</p>
                <p className="mt-1 font-mono text-sm text-paper">{item.value}</p>
              </Card>
            ))}
          </div>

          <Card title="Counts">
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              {Object.entries(status.counts).map(([key, value]) => (
                <div key={key}>
                  <dt className="text-xs text-muted">{key.replaceAll("_", " ")}</dt>
                  <dd className="text-paper">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="Job sources">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead>
                  <tr className="border-b border-line text-xs text-muted">
                    <th className="py-2 pr-3 font-medium">Source</th>
                    <th className="py-2 pr-3 font-medium">Configured</th>
                    <th className="py-2 pr-3 font-medium">Credentials</th>
                    <th className="py-2 pr-3 font-medium">Jobs stored</th>
                    <th className="py-2 font-medium">Notes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {status.sources.map((source) => (
                    <tr key={source.key} className="align-top">
                      <td className="py-2 pr-3 text-paper">{source.display_name}</td>
                      <td className="py-2 pr-3">
                        <span className={source.configured ? "text-signal" : "text-muted"}>
                          {source.configured ? "yes" : "no"}
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted">
                        {source.requires_credentials ? "required" : "public"}
                      </td>
                      <td className="py-2 pr-3 text-paper">{source.jobs_stored}</td>
                      <td className="py-2 text-xs text-muted">{source.notes ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Deployment notes">
            <ul className="space-y-2 text-sm text-muted">
              <li>
                • Docker Compose runs PostgreSQL 16 + pgvector, the API, the browser worker, the web app, and n8n.
              </li>
              <li>
                • Terraform under <span className="font-mono text-paper">infra/terraform</span> provisions AWS
                (VPC/ECS/RDS/S3/ALB). No cloud resources have been created from this session; there are no AWS
                credentials here, so a real deployment cannot be verified from this machine.
              </li>
              <li>• Secrets are supplied through environment variables/SSM; none are stored in the repository.</li>
              <li>
                • LinkedIn, Indeed and Naukri remain credential-gated official-API stubs. They never scrape and never
                bypass a login.
              </li>
            </ul>
            <p className="mt-3 text-xs text-muted">Checked {formatDate(status.checked_at)}</p>
          </Card>
        </>
      ) : null}
    </div>
  );
}
