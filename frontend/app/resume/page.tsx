"use client";

import { useEffect, useRef, useState } from "react";
import { Download, FileText, Star, Trash2 } from "lucide-react";
import {
  Button,
  Card,
  Empty,
  Notice,
  PageHeader,
  Spinner,
  formatDate,
} from "@/components/ui";
import { api, ApiError, type Profile, type ResumeFile } from "@/lib/api";

export default function ResumePage() {
  const [files, setFiles] = useState<ResumeFile[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [useLlm, setUseLlm] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function refresh() {
    const [resumeList, candidate] = await Promise.all([api.listResumes(), api.getProfile()]);
    setFiles(resumeList);
    setProfile(candidate);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof ApiError && err.status === 401 ? "Sign in to manage resumes." : err.message))
      .finally(() => setLoading(false));
  }, []);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.uploadResume(file, useLlm);
      setNotice(
        `Parsed ${result.file.original_filename} with ${result.version.extraction_method}. Profile completeness: ${result.completeness}%.`,
      );
      if (result.warnings.length) setError(result.warnings.join(" "));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function download(file: ResumeFile) {
    try {
      const blob = await api.downloadResume(file.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.original_filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Resume Manager"
        description="Upload a PDF or DOCX. Parsing is deterministic first; the optional AI pass can only confirm values that appear in the document."
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}

      <Card title="Upload">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload(file);
            }}
            className="text-sm text-muted file:mr-3 file:rounded-md file:border file:border-line file:bg-panel-raised file:px-3 file:py-2 file:text-sm file:text-paper"
          />
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />
            Use AI refinement when configured
          </label>
          {busy ? <Spinner label="Parsing…" /> : null}
        </div>
        <p className="mt-3 text-xs text-muted">
          Limits: 5 MB, 20 pages, PDF or DOCX. Scanned PDFs are rejected with a clear error instead of silently
          inventing text.
        </p>
      </Card>

      {profile ? (
        <Card title="What was extracted">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted">Name</dt>
              <dd className="text-paper">{profile.full_name ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Contact email</dt>
              <dd className="text-paper">{profile.email ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Location</dt>
              <dd className="text-paper">{profile.location ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Experience</dt>
              <dd className="text-paper">
                {profile.total_experience_years !== null ? `${profile.total_experience_years} years` : "—"}
              </dd>
            </div>
          </dl>
          <div className="mt-3">
            <p className="text-xs text-muted">Skills recognised literally in the document</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {(profile.skills ?? []).map((skill) => (
                <span key={skill} className="rounded border border-line px-2 py-0.5 text-[11px] text-paper">
                  {skill}
                </span>
              ))}
              {!(profile.skills ?? []).length ? <span className="text-xs text-muted">None yet.</span> : null}
            </div>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-muted">
              <span>Profile completeness</span>
              <span className="font-mono text-paper">{profile.completeness}%</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line">
              <div className="h-full bg-signal" style={{ width: `${profile.completeness}%` }} />
            </div>
          </div>
        </Card>
      ) : null}

      <Card title="Your resumes">
        {loading ? (
          <Spinner />
        ) : files.length ? (
          <ul className="divide-y divide-line">
            {files.map((file) => (
              <li key={file.id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div className="flex min-w-0 items-start gap-3">
                  <FileText size={18} className="mt-0.5 text-muted" />
                  <div className="min-w-0">
                    <p className="truncate text-sm text-paper">
                      {file.original_filename}{" "}
                      {file.is_primary ? (
                        <span className="ml-1 rounded border border-signal/50 px-1.5 py-0.5 text-[10px] text-signal">
                          primary
                        </span>
                      ) : null}
                    </p>
                    <p className="text-xs text-muted">
                      {file.file_type.toUpperCase()} · {(file.size_bytes / 1024).toFixed(0)} KB · {file.status} ·{" "}
                      {formatDate(file.parsed_at ?? file.created_at)}
                    </p>
                  </div>
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => download(file)} title="Download">
                    <Download size={14} />
                  </Button>
                  {!file.is_primary ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      title="Make primary"
                      onClick={async () => {
                        await api.setPrimaryResume(file.id);
                        await refresh();
                      }}
                    >
                      <Star size={14} />
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    title="Re-parse"
                    onClick={async () => {
                      setBusy(true);
                      try {
                        const result = await api.reparseResume(file.id, useLlm);
                        setNotice(`Re-parsed with ${result.version.extraction_method}.`);
                        await refresh();
                      } catch (err) {
                        setError(err instanceof Error ? err.message : "Re-parse failed");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Re-parse
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    title="Delete"
                    onClick={async () => {
                      if (!window.confirm("Delete this resume? Existing applications keep their snapshot.")) return;
                      await api.deleteResume(file.id);
                      await refresh();
                    }}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="No resume uploaded yet">Upload a PDF or DOCX to populate your profile and enable applications.</Empty>
        )}
      </Card>
    </div>
  );
}
