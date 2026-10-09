"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

/** Native <dialog>: focus trapping, Esc and the top layer come from the browser. */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const silentClose = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
    return () => {
      // Cache Components keeps a page mounted but hidden after navigating away. A modal
      // left open there stays in the top layer and makes the new page ignore the pointer.
      // Close it without telling the parent: if the user comes back, the effect re-runs
      // and re-opens it, the same way Next preserves the rest of the page's state.
      if (el.open) {
        silentClose.current = true;
        el.close();
      }
    };
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={() => {
        if (silentClose.current) {
          silentClose.current = false;
          return;
        }
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={`m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] overflow-y-auto ${wide ? "max-w-3xl" : "max-w-md"} rounded-lg border border-line bg-surface p-0 text-ink shadow-lg backdrop:bg-ink/30`}
    >
      {open && (
        <div className="panel-brand p-6">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold">{title}</h2>
              {description && <p className="mt-1 text-sm text-ink-2">{description}</p>}
            </div>
            <button type="button" className="btn btn-quiet btn-sm -mr-2" aria-label="Close" onClick={onClose}>
              <X className="size-4" aria-hidden />
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
