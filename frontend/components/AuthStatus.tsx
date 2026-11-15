"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

export function AuthStatus() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api
      .me()
      .then((user) => setEmail(user.email))
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) setEmail(null);
      })
      .finally(() => setChecked(true));
  }, []);

  if (!checked) return <span className="text-xs text-muted">checking session…</span>;

  if (!email) {
    return (
      <Link href="/login" className="text-sm text-muted hover:text-paper">
        Sign in
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="hidden text-muted sm:inline">{email}</span>
      <button
        onClick={async () => {
          try {
            await api.logout();
          } finally {
            setEmail(null);
            router.push("/login");
            router.refresh();
          }
        }}
        className="text-muted hover:text-paper"
      >
        Sign out
      </button>
    </div>
  );
}
