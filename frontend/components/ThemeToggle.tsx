"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

export function ThemeToggle() {
  // Defaults to dark — this dashboard is designed to be glanced at while an
  // agent works in the background, so dark is the primary experience.
  const [dark, setDark] = useState(true);

  useEffect(() => {
    const stored = window.localStorage.getItem("jobpilot-theme");
    const isDark = stored ? stored === "dark" : true;
    setDark(isDark);
    document.documentElement.classList.toggle("dark", isDark);
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    window.localStorage.setItem("jobpilot-theme", next ? "dark" : "light");
  }

  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="flex h-8 w-8 items-center justify-center rounded-md border border-line text-muted hover:text-paper"
    >
      {dark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
