"use client";

import { formatNumber } from "@/lib/format";

export interface BarDatum {
  name: string;
  value: number;
}

/**
 * Ranked horizontal bars: label, bar, value at the tip. One series, graphite marks.
 * The values are printed, so this doubles as its own table view.
 */
export function BarList({
  data,
  limit,
  emptyLabel = "Nothing to show for this period.",
  onSelect,
  selected,
  ariaLabel,
}: {
  data: BarDatum[];
  limit?: number;
  emptyLabel?: string;
  onSelect?: (name: string) => void;
  selected?: string[];
  ariaLabel: string;
}) {
  const rows = (limit ? data.slice(0, limit) : data).filter((d) => d.value > 0 || data.length <= 8);
  const max = Math.max(1, ...rows.map((d) => d.value));
  if (!rows.length || rows.every((d) => d.value === 0)) {
    return <p className="py-6 text-center text-sm text-ink-3">{emptyLabel}</p>;
  }
  return (
    <ul aria-label={ariaLabel} className="grid gap-1.5">
      {rows.map((d) => {
        const pct = (d.value / max) * 100;
        const isSelected = selected?.includes(d.name);
        const content = (
          <>
            <span className="truncate text-left text-[13px] text-ink-2" title={d.name}>
              {d.name}
            </span>
            <span className="relative h-3.5" aria-hidden>
              {/* 4px rounded data-end, square at the baseline */}
              <span
                className={`absolute inset-y-0 left-0 rounded-r ${isSelected ? "bg-accent-600" : "bg-data"} transition-[width] duration-300`}
                style={{ width: `max(${pct}%, 2px)` }}
              />
            </span>
            <span className="tabular text-right text-[13px] font-medium text-ink">{formatNumber(d.value)}</span>
          </>
        );
        const cls = "grid grid-cols-[minmax(0,9.5rem)_1fr_3.5rem] items-center gap-3 rounded-sm px-1 py-0.5";
        return (
          <li key={d.name}>
            {onSelect ? (
              <button
                type="button"
                className={`${cls} w-full hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-200`}
                aria-pressed={isSelected}
                aria-label={`${d.name}: ${formatNumber(d.value)}`}
                onClick={() => onSelect(d.name)}
              >
                {content}
              </button>
            ) : (
              <div className={cls}>{content}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
