import { formatCompact } from "@/lib/format";

/** label · value · optional context line. Proportional figures at display size. */
export function StatTile({
  label,
  value,
  context,
  tone,
  meter,
}: {
  label: string;
  value: number | string;
  context?: React.ReactNode;
  tone?: "ok" | "warn" | "critical";
  /** 0..1 fill for a same-ramp meter under the value */
  meter?: number;
}) {
  const toneText = tone === "critical" ? "text-critical" : tone === "warn" ? "text-warn" : tone === "ok" ? "text-ok" : "text-ink";
  const meterFill = tone === "critical" ? "bg-critical" : tone === "warn" ? "bg-warn" : "bg-data";
  return (
    <div className="panel p-4">
      <p className="eyebrow">{label}</p>
      <p className={`mt-1 text-[28px] leading-tight font-bold tracking-tight ${toneText}`}>
        {typeof value === "number" ? formatCompact(value) : value}
      </p>
      {meter != null && (
        <div className="mt-2 h-1.5 rounded-full bg-surface-3" aria-hidden>
          <div className={`h-full rounded-full ${meterFill}`} style={{ width: `${Math.min(100, Math.max(0, meter * 100))}%` }} />
        </div>
      )}
      {context && <p className="mt-1.5 text-xs text-ink-3">{context}</p>}
    </div>
  );
}
