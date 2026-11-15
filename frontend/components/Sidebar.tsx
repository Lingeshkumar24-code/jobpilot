"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS } from "@/lib/nav";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex md:w-60 md:flex-col md:border-r md:border-line md:bg-panel">
      <div className="flex items-center gap-2 px-5 py-5">
        <span className="h-2 w-2 rounded-full bg-amber" aria-hidden />
        <span className="font-display text-lg tracking-tight">JobPilot</span>
      </div>

      <nav className="flex-1 px-2 py-2">
        <ul className="space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href;
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                    active
                      ? "bg-panel-raised text-paper"
                      : "text-muted hover:bg-panel-raised hover:text-paper"
                  }`}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon size={17} strokeWidth={1.75} />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-line px-5 py-4 text-xs text-muted">
        Every submission needs your approval. Always.
      </div>
    </aside>
  );
}
