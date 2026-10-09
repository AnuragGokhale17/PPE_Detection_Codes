"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";

import { ppeKey, type ClassRow, type PpeItemRow } from "../_shared/types";

const MIN = 0.05;
const MAX = 0.99;

function clamp(v: number) {
  return Math.min(MAX, Math.max(MIN, Math.round(v * 100) / 100));
}

export function ClassRegistry({ classes, ppeItems }: { classes: ClassRow[]; ppeItems: PpeItemRow[] }) {
  const names = new Map(ppeItems.map((p) => [p.id, p.display_name]));
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="border-b border-line bg-surface-2 text-xs text-ink-3">
          <tr>
            <th scope="col" className="w-14 px-4 py-2.5 font-medium">Id</th>
            <th scope="col" className="px-3 py-2.5 font-medium">Class</th>
            <th scope="col" className="px-3 py-2.5 font-medium">PPE</th>
            <th scope="col" className="px-3 py-2.5 font-medium">Confidence threshold</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Detection</th>
          </tr>
        </thead>
        <tbody>
          {classes.map((c) => (
            <ClassRowView key={`${c.class_id}-${c.threshold}-${c.enabled}`} cls={c} ppeName={c.ppe_item_id ? names.get(c.ppe_item_id) : undefined} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClassRowView({ cls, ppeName }: { cls: ClassRow; ppeName?: string }) {
  const queryClient = useQueryClient();
  const [threshold, setThreshold] = useState(cls.threshold);
  const update = useMutation({
    mutationFn: (json: { threshold?: number; enabled?: boolean }) => api(`/config/classes/${cls.class_id}`, { method: "PATCH", json }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ppeKey }),
  });
  const dirty = Math.abs(threshold - cls.threshold) > 1e-9;
  const inputId = `threshold-${cls.class_id}`;

  return (
    <tr className={`border-b border-line align-top last:border-0 ${cls.enabled ? "" : "text-ink-3"}`}>
      <td className="tabular px-4 py-3 text-ink-3">{cls.class_id}</td>
      <td className="px-3 py-3">
        <p className="font-medium text-ink">{cls.name}</p>
        <div className="mt-1 flex flex-wrap gap-1">
          {cls.is_violation ? <span className="pill pill-critical">Violation</span> : <span className="pill pill-ok">Compliant</span>}
          {!cls.in_active_model && <span className="pill pill-warn">Not in active model yet</span>}
        </div>
      </td>
      <td className="px-3 py-3 text-ink-2">{ppeName ?? "—"}</td>
      <td className="px-3 py-3">
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (dirty) update.mutate({ threshold: clamp(threshold) });
          }}
        >
          <label htmlFor={inputId} className="sr-only">
            Confidence threshold for {cls.name}
          </label>
          <input
            type="range"
            min={MIN}
            max={MAX}
            step={0.01}
            value={threshold}
            aria-label={`Confidence threshold for ${cls.name} (slider)`}
            className="w-28 accent-[var(--accent-600)]"
            onChange={(e) => setThreshold(clamp(Number(e.target.value)))}
          />
          <input
            id={inputId}
            type="number"
            min={MIN}
            max={MAX}
            step={0.01}
            className="input tabular h-8 w-20 px-2"
            value={threshold}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (!Number.isNaN(v)) setThreshold(v);
            }}
            onBlur={() => setThreshold((v) => clamp(v))}
          />
          {dirty && (
            <>
              <button type="submit" className="btn btn-ink btn-sm" disabled={update.isPending}>
                {update.isPending && <Spinner />} Save
              </button>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => setThreshold(cls.threshold)}>
                Reset
              </button>
            </>
          )}
        </form>
        {update.isError && <p className="mt-1 text-xs text-critical">{update.error.message}</p>}
      </td>
      <td className="px-4 py-3">
        <Switch
          checked={cls.enabled}
          disabled={update.isPending}
          onChange={(enabled) => update.mutate({ enabled })}
          label={cls.enabled ? "On" : "Off"}
        />
      </td>
    </tr>
  );
}

export function AddClassDialog({ open, ppeItems, onClose }: { open: boolean; ppeItems: PpeItemRow[]; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add detection class"
      description="New classes get the next free id. Ids are never reused, because the model's outputs are indexed by them."
    >
      {open && <AddClassForm ppeItems={ppeItems} onDone={onClose} />}
    </Dialog>
  );
}

function AddClassForm({ ppeItems, onDone }: { ppeItems: PpeItemRow[]; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [ppeItemId, setPpeItemId] = useState<string>("");
  const [isViolation, setIsViolation] = useState(false);
  const [threshold, setThreshold] = useState(0.6);
  const create = useMutation({
    mutationFn: () =>
      api("/config/classes", {
        method: "POST",
        json: {
          name,
          ppe_item_id: ppeItemId ? Number(ppeItemId) : null,
          is_violation: isViolation,
          threshold: clamp(threshold),
        },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ppeKey });
      onDone();
    },
  });

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      {create.isError && <Alert tone="critical">{create.error.message}</Alert>}
      <div>
        <label htmlFor="class-name" className="label">Class name</label>
        <input
          id="class-name"
          className="input"
          required
          autoFocus
          maxLength={100}
          placeholder="e.g. No Harness"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <p className="mt-1.5 text-xs text-ink-3">Must match the name the retrained model will output.</p>
      </div>
      <div>
        <label htmlFor="class-ppe" className="label">PPE type</label>
        <select id="class-ppe" className="input" value={ppeItemId} onChange={(e) => setPpeItemId(e.target.value)}>
          <option value="">None</option>
          {ppeItems.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
        </select>
      </div>
      <Switch
        checked={isViolation}
        onChange={setIsViolation}
        label="This class is a violation"
        description="Violation classes raise alerts; compliant classes only count towards compliance."
      />
      <div>
        <label htmlFor="class-threshold" className="label">Confidence threshold</label>
        <input
          id="class-threshold"
          type="number"
          min={MIN}
          max={MAX}
          step={0.01}
          className="input tabular w-28"
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
        />
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className="btn btn-ink" disabled={create.isPending || !name.trim()}>
          {create.isPending && <Spinner />} Add class
        </button>
      </div>
    </form>
  );
}
