"use client";

import { daysAgo, isoDate } from "@/lib/format";

export interface DateRange {
  start_date: string;
  end_date: string;
}

export const PRESETS: Array<{ id: string; label: string; range: () => DateRange }> = [
  { id: "today", label: "Today", range: () => ({ start_date: isoDate(new Date()), end_date: isoDate(new Date()) }) },
  { id: "yesterday", label: "Yesterday", range: () => ({ start_date: isoDate(daysAgo(1)), end_date: isoDate(daysAgo(1)) }) },
  { id: "7d", label: "Last 7 days", range: () => ({ start_date: isoDate(daysAgo(6)), end_date: isoDate(new Date()) }) },
  { id: "30d", label: "Last 30 days", range: () => ({ start_date: isoDate(daysAgo(29)), end_date: isoDate(new Date()) }) },
  { id: "90d", label: "Last 90 days", range: () => ({ start_date: isoDate(daysAgo(89)), end_date: isoDate(new Date()) }) },
];

/** Presets first (what people reach for), custom dates behind them. */
export function DateRangePicker({
  preset,
  range,
  onChange,
}: {
  preset: string;
  range: DateRange;
  onChange: (preset: string, range: DateRange) => void;
}) {
  return (
    <div>
      <span className="eyebrow mb-1 block">Period</span>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Period presets" className="flex flex-wrap rounded-md border border-line bg-surface p-0.5">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              aria-pressed={preset === p.id}
              onClick={() => onChange(p.id, p.range())}
              className={`rounded-[5px] px-2.5 py-1 text-[13px] font-medium transition ${
                preset === p.id ? "bg-accent-50 text-accent-700" : "text-ink-2 hover:bg-surface-3"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <label className="sr-only" htmlFor="range-start">From</label>
          <input
            id="range-start"
            type="date"
            className="input h-9 w-[9.5rem] text-[13px]"
            value={range.start_date}
            max={range.end_date}
            onChange={(e) => e.target.value && onChange("custom", { ...range, start_date: e.target.value })}
          />
          <span className="text-ink-3" aria-hidden>–</span>
          <label className="sr-only" htmlFor="range-end">To</label>
          <input
            id="range-end"
            type="date"
            className="input h-9 w-[9.5rem] text-[13px]"
            value={range.end_date}
            min={range.start_date}
            max={isoDate(new Date())}
            onChange={(e) => e.target.value && onChange("custom", { ...range, end_date: e.target.value })}
          />
        </div>
      </div>
    </div>
  );
}
