"use client";

import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

/** Button + popover checklist with search. Selection order follows the option order. */
export function MultiSelect({
  label,
  options,
  value,
  onChange,
  allLabel = "All",
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (next: string[]) => void;
  allLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.toLowerCase().includes(q)) : options;
  }, [options, query]);

  const summary = value.length === 0 ? allLabel : value.length === 1 ? value[0] : `${value.length} selected`;
  const toggle = (o: string) => onChange(value.includes(o) ? value.filter((v) => v !== o) : options.filter((x) => x === o || value.includes(x)));

  return (
    <div ref={root} className="relative">
      <span id={`${id}-label`} className="eyebrow mb-1 block">
        {label}
      </span>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label`}
        className={`input flex h-9 min-w-[150px] items-center justify-between gap-2 text-left ${value.length ? "border-accent-200 bg-accent-50 text-accent-700" : ""}`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="truncate text-[13px]">{summary}</span>
        <ChevronDown className="size-4 shrink-0 text-ink-3" aria-hidden />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-72 max-w-[calc(100vw-2rem)] rounded-md border border-line bg-surface shadow-lg">
          {options.length > 8 && (
            <div className="relative border-b border-line p-2">
              <Search className="pointer-events-none absolute top-1/2 left-4 size-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
              <input
                autoFocus
                className="input h-8 pl-7 text-[13px]"
                placeholder={`Search ${label.toLowerCase()}`}
                aria-label={`Search ${label.toLowerCase()}`}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          )}
          <ul role="listbox" aria-multiselectable aria-labelledby={`${id}-label`} className="max-h-64 overflow-y-auto p-1">
            {visible.map((o) => {
              const selected = value.includes(o);
              return (
                <li key={o} role="option" aria-selected={selected}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[13px] hover:bg-surface-3"
                    onClick={() => toggle(o)}
                  >
                    <span className={`flex size-4 shrink-0 items-center justify-center rounded-[3px] border ${selected ? "border-accent-600 bg-accent-600 text-white" : "border-line-strong"}`}>
                      {selected && <Check className="size-3" strokeWidth={3} aria-hidden />}
                    </span>
                    <span className="truncate">{o}</span>
                  </button>
                </li>
              );
            })}
            {visible.length === 0 && <li className="px-2 py-3 text-center text-xs text-ink-3">No matches</li>}
          </ul>
          {value.length > 0 && (
            <div className="border-t border-line p-1.5">
              <button type="button" className="btn btn-quiet btn-sm w-full" onClick={() => onChange([])}>
                Clear selection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
