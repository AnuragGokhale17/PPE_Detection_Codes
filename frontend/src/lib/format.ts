const dateTime = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" });
const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat("en-IN");

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  return dateTime.format(typeof value === "string" ? new Date(value) : value);
}

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  // "2026-10-08" is a calendar date; don't let the timezone shift it
  const d = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
  return dateOnly.format(d);
}

export function formatNumber(n: number | null | undefined): string {
  return n == null ? "—" : whole.format(n);
}

/** 1,284 / 12.9K / 4.2M — for standalone figures, not columns. */
export function formatCompact(n: number): string {
  return Math.abs(n) < 10_000 ? whole.format(n) : compact.format(n);
}

export function formatPercent(n: number | null | undefined, digits = 1): string {
  return n == null ? "—" : `${(n * 100).toFixed(digits)}%`;
}

export function relativeTime(value: string | Date | null | undefined): string {
  if (!value) return "never";
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDateTime(value);
}

/** yyyy-mm-dd in local time (the plant's calendar), for API date filters. */
export function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function daysAgo(n: number): Date {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
