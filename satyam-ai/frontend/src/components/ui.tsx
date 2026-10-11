import type { Stance } from "../types";
export const STANCE: Record<Stance, { label: string; cls: string }> = {
  supports_manipulation: { label: "Hints at manipulation", cls: "bg-[#FFE0A3] text-[#6B3A00]" },
  supports_authenticity: { label: "Leans authentic", cls: "bg-[#BDEBDD] text-[#0B5A43]" },
  inconclusive: { label: "Inconclusive", cls: "bg-[#E3E0F5] text-[#3C3860]" },
  could_not_check: { label: "Could not check", cls: "bg-white border border-dashed border-[#9A93C4] text-[#4A4670]" },
};
export const Chip = ({ stance }: { stance: Stance }) => <span className={`inline-block rounded-full px-3 py-1 text-xs font-bold ${STANCE[stance].cls}`}>{STANCE[stance].label}</span>;
export const Card = ({ children, className = "" }: { children: React.ReactNode; className?: string }) => <div className={`rounded-3xl bg-white p-6 ${className}`}>{children}</div>;
export const Btn = ({ children, onClick, kind = "primary", disabled, href }: { children: React.ReactNode; onClick?: () => void; kind?: "primary" | "ghost" | "dark"; disabled?: boolean; href?: string }) => {
  const cls = `rounded-2xl px-6 py-3 font-bold text-sm transition disabled:opacity-50 ${kind === "primary" ? "bg-violet text-white hover:brightness-110" : kind === "dark" ? "bg-ink text-white" : "border border-[#D4CCFF] bg-white text-ink hover:bg-violet-soft"}`;
  return href ? <a className={cls + " inline-block"} href={href}>{children}</a> : <button className={cls} onClick={onClick} disabled={disabled}>{children}</button>;
};
export const mb = (n: number) => (n / 1048576).toFixed(1) + " MB";
