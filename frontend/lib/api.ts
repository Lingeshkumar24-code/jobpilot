// Cookie-based API client. The session cookie is httpOnly, so no token ever
// touches localStorage. Every request includes credentials and the backend
// checks Origin on unsafe methods.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE === undefined
    ? "http://localhost:8000"
    : process.env.NEXT_PUBLIC_API_BASE;

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") return record.message;
    if (typeof record.detail === "string") return record.detail;
    if (Array.isArray(record.missing_required) && record.missing_required.length) {
      return `Needs input: ${record.missing_required.join(", ")}`;
    }
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...(options.headers ?? {}),
    },
  });
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : body;
    throw new ApiError(messageFrom(detail, res.status), res.status, detail);
  }
  return body as T;
}

async function requestBlob(path: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!res.ok) {
    throw new ApiError(`Download failed (${res.status})`, res.status);
  }
  return res.blob();
}

export type User = { id: string; email: string; is_active: boolean; full_name?: string | null };

export type Profile = {
  email: string | null;
  full_name: string | null;
  phone: string | null;
  location: string | null;
  headline: string | null;
  summary: string | null;
  linkedin_url: string | null;
  github_url: string | null;
  portfolio_url: string | null;
  experience_level: string | null;
  total_experience_years: number | null;
  current_title: string | null;
  current_company: string | null;
  expected_salary: number | null;
  skills: string[] | null;
  education: Record<string, unknown>[] | null;
  experience: Record<string, unknown>[] | null;
  preferred_roles: string[] | null;
  preferred_locations: string[] | null;
  preferred_work_modes: string[] | null;
  completeness: number;
};

export type ResumeFile = {
  id: string;
  original_filename: string;
  file_type: string;
  size_bytes: number;
  status: string;
  is_primary: boolean;
  error: string | null;
  parsed_at: string | null;
  created_at: string;
};

export type ResumeVersion = {
  id: string;
  resume_file_id: string;
  version_number: number;
  extraction_method: string;
  is_active: boolean;
  parsed_json: Record<string, unknown> | null;
  created_at: string;
};

export type StructuredFilters = {
  role: string[];
  location: string[];
  experience: string | null;
  minimum_salary: number | null;
  maximum_salary: number | null;
  employment_type: string[];
  work_mode: string[];
  skills: string[];
  posted_within_days: number | null;
  internship_with_ppo: boolean;
  minimum_experience_years: number | null;
  maximum_experience_years: number | null;
  notes: string[];
};

export type MatchExplanation = {
  score: number;
  summary: string;
  components: Record<string, { score: number | null; reason: string; matched?: string[] }>;
  weights_used: Record<string, number>;
  matched_skills: string[];
  missing_skills: string[];
  strengths: string[];
  engine: string;
  scored_at: string;
};

export type Job = {
  id: string;
  title: string;
  company: string;
  location: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  work_mode: string | null;
  employment_type: string | null;
  experience_requirement: string | null;
  description: string | null;
  application_url: string;
  source_url: string | null;
  source: string | null;
  source_display_name: string | null;
  posted_at: string | null;
  last_verified_at: string | null;
  is_active: boolean;
  skills: string[];
  match_score: number | null;
  match_explanation: MatchExplanation | null;
};

export type SourceResult = {
  key: string;
  display_name: string;
  status: string;
  count: number;
  message: string;
  attribution: string;
  requires_credentials: boolean;
  duration_ms: number;
};

export type Source = {
  key: string;
  display_name: string;
  base_url: string | null;
  attribution: string | null;
  requires_credentials: boolean;
  is_enabled: boolean;
  configured: boolean;
  last_synced_at: string | null;
  last_sync_error: string | null;
  notes: string | null;
};

export type Answer = {
  id: string;
  field_name: string;
  field_label: string | null;
  field_type: string | null;
  field_value: string | null;
  source: string;
  confidence: number | null;
  is_required: boolean;
  is_user_edited: boolean;
  validation_error: string | null;
};

export type ApplicationEvent = {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type Application = {
  id: string;
  job: { id: string; title: string; company: string; location?: string | null; application_url?: string };
  status: string;
  resume_version_id: string | null;
  preview: Record<string, unknown> | null;
  failure_reason: string | null;
  outcome: string | null;
  approved_at: string | null;
  submitted_at: string | null;
  confirmed_at: string | null;
  submission_attempts: number;
  screenshot_available: boolean;
  approval_expires_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ApplicationDetail = Application & {
  answers: Answer[];
  events: ApplicationEvent[];
  confirmation_evidence: Record<string, unknown> | null;
  browser_session: Record<string, unknown> | null;
};

export type ApplicationStats = {
  total: number;
  by_status: Record<string, number>;
  confirmed: number;
  needs_input: number;
  pending_approval: number;
  interviews: number;
  offers: number;
};

export type Match = {
  id: string;
  job: Job;
  match_score: number;
  match_explanation: MatchExplanation | null;
  is_dismissed: boolean;
  created_at: string;
};

export type AgentStep = {
  node: string;
  label: string;
  status: string;
  detail: string | null;
  at: string;
};

export type AgentRun = {
  id: string;
  thread_id: string;
  goal: string;
  status: string;
  current_node: string | null;
  state: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  interrupt_payload: Record<string, unknown> | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  steps: AgentStep[];
};

export type SystemStatus = {
  environment: string;
  database: string;
  storage_backend: string;
  llm_provider: string;
  browser_worker_configured: boolean;
  browser_worker_reachable: boolean | null;
  n8n_configured: boolean;
  sources: { key: string; display_name: string; configured: boolean; requires_credentials: boolean; jobs_stored: number; notes: string | null }[];
  counts: Record<string, number>;
  checked_at: string;
};

export type Preferences = {
  digest_enabled: boolean;
  digest_time: string | null;
  email_notifications: boolean;
  greenhouse_boards: string[] | null;
  lever_sites: string[] | null;
  preferences: Record<string, unknown> | null;
};

export type Workflow = {
  id: string;
  name: string;
  key: string;
  description: string | null;
  is_active: boolean;
  last_run_at: string | null;
  last_status: string | null;
};

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  register: (email: string, password: string) =>
    request<User>("/api/v1/auth/register", json({ email, password })),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/api/v1/auth/login", json({ email, password })),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/v1/auth/me"),

  getProfile: () => request<Profile>("/api/v1/profile"),
  updateProfile: (updates: Partial<Profile>) =>
    request<Profile>("/api/v1/profile", { method: "PATCH", body: JSON.stringify(updates) }),

  listResumes: () => request<ResumeFile[]>("/api/v1/resumes"),
  getResume: (id: string) =>
    request<{ file: ResumeFile; versions: ResumeVersion[]; active_version: ResumeVersion | null; completeness: number }>(
      `/api/v1/resumes/${id}`,
    ),
  uploadResume: (file: File, useLlm = true) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ file: ResumeFile; version: ResumeVersion; completeness: number; missing_fields: string[]; warnings: string[] }>(
      `/api/v1/resumes/upload?use_llm=${useLlm ? "true" : "false"}`,
      { method: "POST", body: form },
    );
  },
  reparseResume: (id: string, useLlm = true) =>
    request<{ file: ResumeFile; version: ResumeVersion; completeness: number; missing_fields: string[]; warnings: string[] }>(
      `/api/v1/resumes/${id}/reparse`,
      json({ use_llm: useLlm }),
    ),
  setPrimaryResume: (id: string) =>
    request<ResumeFile>(`/api/v1/resumes/${id}/primary`, { method: "POST" }),
  deleteResume: (id: string) => request<void>(`/api/v1/resumes/${id}`, { method: "DELETE" }),
  downloadResume: (id: string) => requestBlob(`/api/v1/resumes/${id}/download`),

  searchIntent: (query: string, previousFilters?: StructuredFilters) =>
    request<{ query: string; filters: StructuredFilters; provider: string; missing: string[] }>(
      "/api/v1/search/intent",
      json({ query, previous_filters: previousFilters ?? null }),
    ),
  search: (query: string, options?: { sources?: string[]; limit?: number; save?: boolean; name?: string }) =>
    request<{
      query_id: string;
      filters: StructuredFilters;
      provider: string;
      jobs: Job[];
      sources: SourceResult[];
      warnings: string[];
      total: number;
    }>("/api/v1/search/execute", json({ query, ...options })),
  searchHistory: () =>
    request<{ id: string; raw_text: string; structured_filters: StructuredFilters | null; result_count: number; is_saved: boolean; last_run_at: string | null; created_at: string }[]>(
      "/api/v1/search/history",
    ),
  saveSearch: (id: string, name: string) =>
    request<unknown>(`/api/v1/search/history/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),

  listJobs: (params?: { q?: string; source?: string; limit?: number; offset?: number; min_score?: number }) => {
    const search = new URLSearchParams();
    Object.entries(params ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
    });
    return request<{ jobs: Job[]; total: number; limit: number; offset: number }>(`/api/v1/jobs?${search.toString()}`);
  },
  getJob: (id: string) => request<{ job: Job; source_attribution: string | null; duplicates: unknown[] }>(`/api/v1/jobs/${id}`),
  listSources: () => request<Source[]>("/api/v1/jobs/sources"),

  listMatches: (params?: { q?: string; min_score?: number; include_dismissed?: boolean; limit?: number }) => {
    const search = new URLSearchParams();
    Object.entries(params ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
    });
    return request<{ matches: Match[]; total: number }>(`/api/v1/matches?${search.toString()}`);
  },
  matchStats: () =>
    request<{ total: number; dismissed: number; scored_today: number; average_score: number | null; above_threshold: number }>(
      "/api/v1/matches/stats",
    ),
  dismissMatch: (id: string) => request<Match>(`/api/v1/matches/${id}/dismiss`, { method: "POST" }),

  listApplications: (params?: { status?: string; q?: string; limit?: number }) => {
    const search = new URLSearchParams();
    Object.entries(params ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
    });
    return request<{ applications: Application[]; total: number; counts: Record<string, number> }>(
      `/api/v1/applications?${search.toString()}`,
    );
  },
  getApplication: (id: string) => request<ApplicationDetail>(`/api/v1/applications/${id}`),
  createApplication: (jobId: string, resumeVersionId?: string) =>
    request<Application>("/api/v1/applications", json({ job_id: jobId, resume_version_id: resumeVersionId ?? null })),
  openAndFillApplication: async (jobId: string): Promise<{ id: string; notice?: string }> => {
    let application: Application;
    try {
      application = await request<Application>("/api/v1/applications", json({ job_id: jobId, resume_version_id: null }));
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail as { application_id?: string } | undefined : undefined;
      if (!(error instanceof ApiError) || error.status !== 409 || !detail?.application_id) throw error;
      application = await request<Application>(`/api/v1/applications/${detail.application_id}`);
    }

    let notice: string | undefined;
    try {
      let current = application;
      if (["DISCOVERED", "MATCHED", "APPLICATION_OPENED", "NEEDS_USER_INPUT"].includes(current.status)) {
        current = await request<ApplicationDetail>(`/api/v1/applications/${application.id}/analyze`, { method: "POST" });
      }
      if (["FORM_ANALYZED", "NEEDS_USER_INPUT"].includes(current.status)) {
        await request<ApplicationDetail>(`/api/v1/applications/${application.id}/fill`, { method: "POST" });
        notice = "The application form is filled and verified. Review every answer before requesting submission approval.";
      } else if (current.status === "CAPTCHA_REQUIRED" || current.status === "LOGIN_REQUIRED") {
        notice = "The employer requires a login or CAPTCHA. JobPilot stopped so you can complete that step manually.";
      } else if (["FORM_FILLED", "VERIFICATION_PENDING", "USER_APPROVAL_PENDING"].includes(current.status)) {
        notice = "This application is already filled. Review the answers before requesting submission approval.";
      }
    } catch (error) {
      notice = error instanceof Error
        ? `The application was saved, but automatic form filling needs attention: ${error.message}`
        : "The application was saved, but automatic form filling needs attention.";
    }
    return { id: application.id, notice };
  },
  analyzeApplication: (id: string) =>
    request<ApplicationDetail>(`/api/v1/applications/${id}/analyze`, { method: "POST" }),
  fillApplication: (id: string) =>
    request<ApplicationDetail>(`/api/v1/applications/${id}/fill`, { method: "POST" }),
  updateAnswer: (id: string, answerId: string, value: string) =>
    request<Answer>(`/api/v1/applications/${id}/answers/${answerId}`, {
      method: "PATCH",
      body: JSON.stringify({ field_value: value }),
    }),
  requestApproval: (id: string) =>
    request<{ application_id: string; approval_token: string; expires_at: string; summary: Record<string, unknown> }>(
      `/api/v1/applications/${id}/approval/request`,
      { method: "POST" },
    ),
  approve: (id: string, token: string) =>
    request<{ application: Application; proof: Record<string, unknown> }>(
      `/api/v1/applications/${id}/approve`,
      json({ token }),
    ),
  submit: (id: string, proof: Record<string, unknown>) =>
    request<{
      application: Application;
      outcome: string | null;
      evidence: Record<string, unknown> | null;
      validation_errors: string[];
    }>(`/api/v1/applications/${id}/submit`, json({ proof })),
  reject: (id: string, reason?: string) =>
    request<Application>(`/api/v1/applications/${id}/reject`, json({ reason: reason ?? null })),
  confirmManual: (id: string, evidence: string) =>
    request<Application>(`/api/v1/applications/${id}/confirm-manual`, json({ evidence })),
  recordOutcome: (id: string, outcome: string, note?: string) =>
    request<Application>(`/api/v1/applications/${id}/outcome`, json({ outcome, note: note ?? null })),
  applicationStats: () =>
    request<ApplicationStats>("/api/v1/applications/stats"),
  applicationScreenshot: (id: string) => requestBlob(`/api/v1/applications/${id}/screenshot`),
  applicationBrowserFrame: (id: string) => requestBlob(`/api/v1/applications/${id}/browser-frame`),
  applicationBrowserStreamTicket: (id: string) =>
    request<{ ticket: string; expires_at: string }>(`/api/v1/applications/${id}/browser-stream-ticket`, { method: "POST" }),
  applicationBrowserStreamUrl: (id: string, ticket: string) => {
    const url = new URL(`/api/v1/applications/${id}/browser-stream`, API_BASE || window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("ticket", ticket);
    return url.toString();
  },
  openBrowserSearch: (provider: "google" | "linkedin" | "indeed", query: string) =>
    request<{ session_id: string; provider: string; query: string; url: string; title: string; ticket: string; expires_at: string }>(
      "/api/v1/browser/search/open",
      json({ provider, query }),
    ),
  driveBrowserSearch: (ticket: string, allowScreenshotToOpenRouter: boolean) =>
    request<{
      provider: string;
      query: string;
      steps: { action: string; target: string; reason: string }[];
      outcome: string;
      url: string | null;
      title: string | null;
      screenshot: { mime: string; base64: string } | null;
    }>("/api/v1/browser/search/drive", json({ ticket, max_actions: 6, allow_screenshot_to_openrouter: allowScreenshotToOpenRouter })),
  browserSearchStreamUrl: (ticket: string) => {
    const url = new URL("/api/v1/browser/search/stream", API_BASE || window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("ticket", ticket);
    return url.toString();
  },

  listAgentRuns: () =>
    request<{ runs: AgentRun[]; total: number }>("/api/v1/agents/runs"),
  startAgentRun: (goal: string, prepareApplications: boolean, limit = 5) =>
    request<AgentRun>("/api/v1/agents/runs", json({ goal, prepare_applications: prepareApplications, limit })),
  resumeAgentRun: (id: string, approved: boolean, applicationId?: string, proof?: Record<string, unknown>) =>
    request<AgentRun>(
      `/api/v1/agents/runs/${id}/resume`,
      json({ approved, application_id: applicationId ?? null, proof: proof ?? null }),
    ),
  cancelAgentRun: (id: string) =>
    request<AgentRun>(`/api/v1/agents/runs/${id}/cancel`, { method: "POST" }),

  listWorkflows: () => request<Workflow[]>("/api/v1/automation/workflows"),
  triggerWorkflow: (key: string) =>
    request<{ accepted: boolean; run_id: string | null; message: string }>(
      `/api/v1/automation/workflows/${key}/trigger`,
      { method: "POST" },
    ),

  getPreferences: () => request<Preferences>("/api/v1/settings/preferences"),
  updatePreferences: (updates: Partial<Preferences>) =>
    request<Preferences>("/api/v1/settings/preferences", { method: "PUT", body: JSON.stringify(updates) }),
  systemStatus: () => request<SystemStatus>("/api/v1/settings/system"),
  auditTrail: (limit = 50) =>
    request<{ id: string; action: string; resource_type: string | null; resource_id: string | null; details: Record<string, unknown> | null; ip_address: string | null; created_at: string }[]>(
      `/api/v1/settings/audit?limit=${limit}`,
    ),
};
