"use client";

import { Check } from "lucide-react";

import type { PpeItemRef } from "./types";

/** Toggle chips for choosing which PPE an area requires. */
export function PpeChipPicker({
  items,
  value,
  onChange,
  disabled,
  legend = "Required PPE",
  hint,
}: {
  items: PpeItemRef[];
  value: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  legend?: string;
  hint?: string;
}) {
  const selected = new Set(value);
  return (
    <fieldset>
      <legend className="label">{legend}</legend>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => {
          const on = selected.has(item.key);
          return (
            <button
              key={item.key}
              type="button"
              aria-pressed={on}
              disabled={disabled || (!item.enabled && !on)}
              onClick={() => {
                const next = new Set(selected);
                if (on) next.delete(item.key);
                else next.add(item.key);
                // Keep the registry's order so diffs read cleanly
                onChange(items.filter((i) => next.has(i.key)).map((i) => i.key));
              }}
              className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-accent-200 disabled:cursor-not-allowed disabled:opacity-50 ${
                on ? "border-accent-600 bg-accent-50 text-accent-700" : "border-line bg-surface text-ink-2 hover:border-line-strong"
              }`}
            >
              {on && <Check className="size-3.5" aria-hidden />}
              {item.display_name}
              {!item.enabled && <span className="text-ink-3">(off)</span>}
            </button>
          );
        })}
      </div>
      {hint && <p className="mt-1.5 text-xs text-ink-3">{hint}</p>}
    </fieldset>
  );
}

/** Read-only chips for tables. */
export function PpeChips({ keys, items }: { keys: string[]; items: PpeItemRef[] }) {
  if (!keys.length) return <span className="text-xs text-ink-3">All enabled PPE</span>;
  const names = new Map(items.map((i) => [i.key, i.display_name]));
  return (
    <div className="flex flex-wrap gap-1">
      {keys.map((k) => (
        <span key={k} className="pill pill-quiet">
          {names.get(k) ?? k}
        </span>
      ))}
    </div>
  );
}
