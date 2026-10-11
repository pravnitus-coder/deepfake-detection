import React from "react";
import type { Stance } from "../types";

export const STANCE: Record<Stance, { label: string; cls: string; dot: string }> = {
  supports_manipulation: {
    label: "Signals Manipulation",
    cls: "bg-amber-950/50 text-amber-200 border border-amber-600/40",
    dot: "bg-amber-400",
  },
  supports_authenticity: {
    label: "Leans Authentic",
    cls: "bg-emerald-950/50 text-emerald-200 border border-emerald-600/40",
    dot: "bg-emerald-400",
  },
  inconclusive: {
    label: "Inconclusive",
    cls: "bg-indigo-950/50 text-indigo-200 border border-indigo-600/40",
    dot: "bg-indigo-400",
  },
  could_not_check: {
    label: "Could Not Check",
    cls: "bg-[#141a2e]/60 text-slate-300 border border-dashed border-slate-600/50",
    dot: "bg-slate-500",
  },
};

export const Chip = ({ stance }: { stance: Stance }) => {
  const meta = STANCE[stance] || STANCE.inconclusive;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${meta.cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden="true" />
      {meta.label}
    </span>
  );
};

export const StatusBadge = ({ status }: { status: "completed" | "unavailable" | "failed" | string }) => {
  const config = {
    completed: "bg-emerald-950/50 text-emerald-300 border-emerald-600/30",
    unavailable: "bg-slate-900/60 text-slate-400 border-slate-700/50",
    failed: "bg-red-950/50 text-red-300 border-red-600/30",
  }[status] || "bg-slate-900/60 text-slate-400 border-slate-700/50";

  return (
    <span className={`inline-block rounded-md border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider ${config}`}>
      {status}
    </span>
  );
};

export const Card = ({ children, className = "" }: { children: React.ReactNode; className?: string }) => (
  <div className={`rounded-2xl border border-[#232b45] bg-[#12172a] p-5 shadow-xl transition ${className}`}>
    {children}
  </div>
);

export const Btn = ({
  children,
  onClick,
  kind = "primary",
  disabled,
  href,
  className = "",
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  kind?: "primary" | "secondary" | "ghost" | "danger" | "dark";
  disabled?: boolean;
  href?: string;
  className?: string;
  title?: string;
}) => {
  const base = "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet focus-visible:ring-offset-2 focus-visible:ring-offset-ground disabled:opacity-40 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-violet text-white hover:brightness-110 shadow-lg shadow-violet/20",
    secondary: "border border-[#2a3456] bg-[#171f38] text-ink hover:bg-[#1e2849] hover:border-violet/60",
    ghost: "border border-[#232b45] bg-transparent text-muted hover:bg-[#182038] hover:text-white",
    danger: "border border-red-800/40 bg-red-950/40 text-red-300 hover:bg-red-900/50 hover:text-white",
    dark: "bg-[#090d19] text-white border border-[#1e253e] hover:bg-[#11172a]",
  }[kind];

  const combined = `${base} ${styles} ${className}`;
  return href ? (
    <a className={combined} href={href} title={title}>
      {children}
    </a>
  ) : (
    <button className={combined} onClick={onClick} disabled={disabled} title={title}>
      {children}
    </button>
  );
};

export function ConfirmModal({
  isOpen,
  title,
  message,
  confirmLabel = "Delete",
  isDanger = true,
  onConfirm,
  onCancel,
}: {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  isDanger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!isOpen) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="w-full max-w-md rounded-3xl border border-[#2a3352] bg-[#12172a] p-6 text-ink shadow-2xl">
        <h3 id="confirm-modal-title" className="font-display text-lg font-extrabold text-white">
          {title}
        </h3>
        <p className="mt-2 text-xs leading-relaxed text-muted">{message}</p>
        <div className="mt-6 flex justify-end gap-2.5">
          <Btn kind="ghost" onClick={onCancel}>
            Cancel
          </Btn>
          <Btn kind={isDanger ? "danger" : "primary"} onClick={onConfirm}>
            {confirmLabel}
          </Btn>
        </div>
      </div>
    </div>
  );
}

export const mb = (n: number) => (n / 1048576).toFixed(1) + " MB";
