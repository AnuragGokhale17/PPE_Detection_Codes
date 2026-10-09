import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

type Tone = "critical" | "warn" | "ok" | "info";

const styles: Record<Tone, string> = {
  critical: "border-critical-line bg-critical-surface text-critical",
  warn: "border-warn-line bg-warn-surface text-warn",
  ok: "border-ok-line bg-ok-surface text-ok",
  info: "border-accent-100 bg-accent-50 text-accent-700",
};

const icons = { critical: AlertTriangle, warn: AlertTriangle, ok: CheckCircle2, info: Info };

export function Alert({ tone = "info", children }: { tone?: Tone; children: React.ReactNode }) {
  const Icon = icons[tone];
  return (
    <div role={tone === "critical" ? "alert" : "status"} className={`flex gap-2.5 rounded-md border px-3 py-2.5 text-[13px] ${styles[tone]}`}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
