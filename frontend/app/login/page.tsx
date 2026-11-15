"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Input, Label, Notice } from "@/components/ui";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "register") {
        await api.register(email, password);
      } else {
        await api.login(email, password);
      }
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm pt-12">
      <h1 className="font-display text-xl text-paper">
        {mode === "login" ? "Sign in" : "Create your account"}
      </h1>
      <p className="mt-1 text-sm text-muted">
        The session is an httpOnly cookie. No token is stored in localStorage.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            required
            minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        {error ? <Notice>{error}</Notice> : null}

        <Button type="submit" variant="primary" className="w-full" disabled={busy}>
          {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>

      <button
        onClick={() => setMode(mode === "login" ? "register" : "login")}
        className="mt-4 text-sm text-muted hover:text-paper"
      >
        {mode === "login" ? "Need an account? Create one" : "Already have an account? Sign in"}
      </button>
    </div>
  );
}
