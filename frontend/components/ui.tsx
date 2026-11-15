"use client";

import { X } from "lucide-react";
import type { ReactNode } from "react";

export function cn(...values: (string | false | null | undefined)[]) {
  return values.filter(Boolean).join(" ");
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="font-display text-2xl tracking-tight text-paper">{title}</h1>
        {description ? <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Card({
  children,
  className,
  title,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  action?: ReactNode;
}) {
  return (
    <section className={cn("rounded-lg border border-line bg-panel", className)}>
      {title ? (
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-medium text-paper">{title}</h2>
          {action}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
};

export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonProps) {
  const styles = {
    primary: "border-amber bg-amber text-ink hover:opacity-90",
    secondary: "border-line bg-panel-raised text-paper hover:border-amber",
    ghost: "border-transparent bg-transparent text-muted hover:text-paper",
    danger: "border-danger text-danger hover:bg-danger hover:text-ink",
  }[variant];
  const sizing = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm";
  return (
    <button
      {...props}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        styles,
        sizing,
        className,
      )}
    />
  );
}

export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-muted">
      {children}
    </label>
  );
}

const fieldClass =
  "w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-paper placeholder:text-muted focus:border-amber";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(fieldClass, props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(fieldClass, "min-h-[90px]", props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(fieldClass, props.className)} />;
}

export function Notice({
  tone = "error",
  children,
}: {
  tone?: "error" | "info" | "success";
  children: ReactNode;
}) {
  const styles = {
    error: "border-danger/50 text-danger",
    info: "border-line text-muted",
    success: "border-signal/60 text-signal",
  }[tone];
  return <div className={cn("rounded-md border px-3 py-2 text-sm", styles)}>{children}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-10 text-center">
      <p className="text-sm text-paper">{title}</p>
      {children ? <div className="mx-auto mt-2 max-w-md text-xs text-muted">{children}</div> : null}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted" role="status">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-amber" />
      {label}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  CONFIRMED: "border-signal/60 text-signal",
  SUBMITTED: "border-signal/40 text-signal",
  APPROVED: "border-amber/60 text-amber",
  USER_APPROVAL_PENDING: "border-amber/60 text-amber",
  VERIFICATION_PENDING: "border-amber/50 text-amber",
  FORM_FILLED: "border-line text-paper",
  FORM_ANALYZED: "border-line text-paper",
  NEEDS_USER_INPUT: "border-danger/50 text-danger",
  CAPTCHA_REQUIRED: "border-danger/50 text-danger",
  LOGIN_REQUIRED: "border-danger/50 text-danger",
  UNKNOWN_SUBMISSION_STATUS: "border-amber/60 text-amber",
  FAILED: "border-danger/60 text-danger",
  CANCELLED: "border-line text-muted",
  DISCOVERED: "border-line text-muted",
  MATCHED: "border-line text-muted",
  APPLICATION_OPENED: "border-line text-paper",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide",
        STATUS_TONE[status] ?? "border-line text-muted",
      )}
    >
      {status.replaceAll("_", " ").toLowerCase()}
    </span>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[85vh] w-full max-w-xl overflow-auto rounded-lg border border-line bg-panel shadow-xl"
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-medium text-paper">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="text-muted hover:text-paper">
            <X size={16} />
          </button>
        </header>
        <div className="px-4 py-4 text-sm text-paper">{children}</div>
        {footer ? <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer> : null}
      </div>
    </div>
  );
}

export function Score({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-xs text-muted">not scored</span>;
  const color = value >= 75 ? "text-signal" : value >= 55 ? "text-amber" : "text-muted";
  return <span className={cn("font-mono text-sm", color)}>{Math.round(value)}%</span>;
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function timeAgo(value: string | null | undefined) {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
