"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Input,
  Notice,
  PageHeader,
  Spinner,
  Textarea,
} from "@/components/ui";
import { api, ApiError, type Profile } from "@/lib/api";

type FormState = {
  full_name: string;
  email: string;
  phone: string;
  location: string;
  headline: string;
  current_title: string;
  current_company: string;
  total_experience_years: string;
  expected_salary: string;
  experience_level: string;
  summary: string;
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  skills: string;
  preferred_roles: string;
  preferred_locations: string;
  preferred_work_modes: string;
  education: string;
  experience: string;
};

function toForm(profile: Profile): FormState {
  return {
    full_name: profile.full_name ?? "",
    email: profile.email ?? "",
    phone: profile.phone ?? "",
    location: profile.location ?? "",
    headline: profile.headline ?? "",
    current_title: profile.current_title ?? "",
    current_company: profile.current_company ?? "",
    total_experience_years:
      profile.total_experience_years === null ? "" : String(profile.total_experience_years),
    expected_salary: profile.expected_salary === null ? "" : String(profile.expected_salary),
    experience_level: profile.experience_level ?? "",
    summary: profile.summary ?? "",
    linkedin_url: profile.linkedin_url ?? "",
    github_url: profile.github_url ?? "",
    portfolio_url: profile.portfolio_url ?? "",
    skills: (profile.skills ?? []).join(", "),
    preferred_roles: (profile.preferred_roles ?? []).join(", "),
    preferred_locations: (profile.preferred_locations ?? []).join(", "),
    preferred_work_modes: (profile.preferred_work_modes ?? []).join(", "),
    education: JSON.stringify(profile.education ?? [], null, 2),
    experience: JSON.stringify(profile.experience ?? [], null, 2),
  };
}

const split = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api
      .getProfile()
      .then((data) => {
        setProfile(data);
        setForm(toForm(data));
      })
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to edit your profile."
            : err instanceof Error
              ? err.message
              : "Could not load your profile",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    if (!form) return;
    setForm({ ...form, [key]: value });
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!form) return;
    setError(null);
    setNotice(null);
    let education: unknown[];
    let experience: unknown[];
    try {
      education = JSON.parse(form.education || "[]");
      experience = JSON.parse(form.experience || "[]");
      if (!Array.isArray(education) || !Array.isArray(experience)) throw new Error("must be arrays");
    } catch {
      setError("Education and experience must be valid JSON arrays.");
      return;
    }
    setSaving(true);
    try {
      const updated = await api.updateProfile({
        full_name: form.full_name || null,
        email: form.email || null,
        phone: form.phone || null,
        location: form.location || null,
        headline: form.headline || null,
        current_title: form.current_title || null,
        current_company: form.current_company || null,
        total_experience_years: form.total_experience_years ? Number(form.total_experience_years) : null,
        expected_salary: form.expected_salary ? Number(form.expected_salary) : null,
        experience_level: form.experience_level || null,
        summary: form.summary || null,
        linkedin_url: form.linkedin_url || null,
        github_url: form.github_url || null,
        portfolio_url: form.portfolio_url || null,
        skills: split(form.skills),
        preferred_roles: split(form.preferred_roles),
        preferred_locations: split(form.preferred_locations),
        preferred_work_modes: split(form.preferred_work_modes),
        education: education as Record<string, unknown>[],
        experience: experience as Record<string, unknown>[],
      });
      setProfile(updated);
      setForm(toForm(updated));
      setNotice("Profile saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your profile");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner label="Loading your profile…" />;

  if (error && !profile) {
    return (
      <div className="max-w-md space-y-3">
        <PageHeader title="Candidate profile" />
        <Notice>{error}</Notice>
        <Link href="/login">
          <Button variant="primary">Sign in</Button>
        </Link>
      </div>
    );
  }

  if (!profile || !form) return null;

  const field = (
    key: keyof FormState,
    label: string,
    options?: { placeholder?: string; type?: string; wide?: boolean },
  ) => (
    <div className={options?.wide ? "sm:col-span-2" : undefined}>
      <label htmlFor={key} className="mb-1 block text-xs text-muted">
        {label}
      </label>
      <Input
        id={key}
        type={options?.type ?? "text"}
        value={form[key]}
        placeholder={options?.placeholder}
        onChange={(event) => update(key, event.target.value)}
      />
    </div>
  );

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Candidate profile"
        description="This is the source of truth for applications. Resume parsing fills it in, and your edits always win."
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="success">{notice}</Notice> : null}

      <Card>
        <div className="mb-4">
          <div className="flex items-center justify-between text-xs text-muted">
            <span>Completeness</span>
            <span className="font-mono text-paper">{profile.completeness}%</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line">
            <div className="h-full bg-signal" style={{ width: `${profile.completeness}%` }} />
          </div>
          <p className="mt-2 text-xs text-muted">
            The contact email here is what employers see; it can differ from your sign-in email.
          </p>
        </div>

        <form onSubmit={save} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {field("full_name", "Full name")}
            {field("email", "Contact email", { type: "email" })}
            {field("phone", "Phone")}
            {field("location", "Location", { placeholder: "Bengaluru, India" })}
            {field("headline", "Headline", { wide: true })}
            {field("current_title", "Current title")}
            {field("current_company", "Current company")}
            {field("total_experience_years", "Years of experience", { type: "number" })}
            {field("experience_level", "Experience level", { placeholder: "fresher / mid / senior" })}
            {field("expected_salary", "Expected salary (annual)", { type: "number" })}
            {field("linkedin_url", "LinkedIn URL")}
            {field("github_url", "GitHub URL")}
            {field("portfolio_url", "Portfolio URL")}
            {field("skills", "Skills (comma separated)", { wide: true })}
            {field("preferred_roles", "Preferred roles (comma separated)")}
            {field("preferred_locations", "Preferred locations (comma separated)")}
            {field("preferred_work_modes", "Preferred work modes", { placeholder: "remote, hybrid" })}
          </div>

          <div>
            <label htmlFor="summary" className="mb-1 block text-xs text-muted">
              Professional summary
            </label>
            <Textarea
              id="summary"
              value={form.summary}
              onChange={(event) => update("summary", event.target.value)}
              placeholder="What you build, in your own words."
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="education" className="mb-1 block text-xs text-muted">
                Education (JSON array)
              </label>
              <Textarea
                id="education"
                value={form.education}
                onChange={(event) => update("education", event.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div>
              <label htmlFor="experience" className="mb-1 block text-xs text-muted">
                Experience (JSON array)
              </label>
              <Textarea
                id="experience"
                value={form.experience}
                onChange={(event) => update("experience", event.target.value)}
                className="font-mono text-xs"
              />
            </div>
          </div>

          <Button type="submit" variant="primary" disabled={saving}>
            {saving ? "Saving…" : "Save profile"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
