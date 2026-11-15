"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthStatus } from "@/components/AuthStatus";
import { ThemeToggle } from "@/components/ThemeToggle";

export function TopBar() {
  const router = useRouter();
  const [query, setQuery] = useState("");

  return (
    <header className="flex items-center gap-4 border-b border-line bg-ink px-6 py-4">
      <form
        className="relative max-w-xl flex-1"
        onSubmit={(event) => {
          event.preventDefault();
          const value = query.trim();
          router.push(value ? `/search?q=${encodeURIComponent(value)}` : "/search");
        }}
      >
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Find GenAI internships with PPO near Bengaluru…"
          className="w-full rounded-md border border-line bg-panel py-2 pl-9 pr-3 text-sm text-paper placeholder:text-muted focus:border-amber"
        />
      </form>
      <AuthStatus />
      <ThemeToggle />
    </header>
  );
}
