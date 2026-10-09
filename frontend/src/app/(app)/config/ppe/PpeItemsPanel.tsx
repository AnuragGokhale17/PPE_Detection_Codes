"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";

import { overviewKey, ppeKey, type PpeItemRow } from "../_shared/types";

function useInvalidate() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ppeKey }),
      queryClient.invalidateQueries({ queryKey: overviewKey }),
    ]);
}

export function PpeItemsPanel({ items }: { items: PpeItemRow[] }) {
  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <PpeItemRowView key={item.id} item={item} />
      ))}
    </ul>
  );
}

function PpeItemRowView({ item }: { item: PpeItemRow }) {
  const invalidate = useInvalidate();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(item.display_name);
  const update = useMutation({
    mutationFn: (json: { display_name?: string; enabled?: boolean }) => api(`/config/ppe-items/${item.id}`, { method: "PATCH", json }),
    onSuccess: async () => {
      await invalidate();
      setEditing(false);
    },
  });

  return (
    <li className="grid gap-2 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        {editing ? (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) update.mutate({ display_name: name.trim() });
            }}
          >
            <label htmlFor={`ppe-name-${item.id}`} className="sr-only">
              Display name for {item.key}
            </label>
            <input
              id={`ppe-name-${item.id}`}
              className="input h-8 max-w-56"
              autoFocus
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button type="submit" className="btn btn-ink btn-sm" disabled={update.isPending || !name.trim()}>
              {update.isPending && <Spinner />} Save
            </button>
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={() => {
                setName(item.display_name);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </form>
        ) : (
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[13px] font-medium text-ink">{item.display_name}</span>
            <span className="font-mono text-[11px] text-ink-3">{item.key}</span>
            <button type="button" className="text-xs font-medium text-accent-700 hover:underline" onClick={() => setEditing(true)}>
              Rename
            </button>
          </div>
        )}
        <p className="tabular text-xs text-ink-3">
          {item.cameras ? `Required in ${item.cameras} enabled camera${item.cameras === 1 ? "" : "s"}` : "Not required by any enabled camera"}
        </p>
        {update.isError && <p className="mt-1 text-xs text-critical">{update.error.message}</p>}
      </div>
      <Switch
        checked={item.enabled}
        disabled={update.isPending}
        onChange={(enabled) => update.mutate({ enabled })}
        label={item.enabled ? "Monitored" : "Off"}
      />
    </li>
  );
}

export function AddPpeDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Add PPE type" description="For example a harness, ear protection or a face shield.">
      {open && <AddPpeForm onDone={onClose} />}
    </Dialog>
  );
}

function AddPpeForm({ onDone }: { onDone: () => void }) {
  const invalidate = useInvalidate();
  const [displayName, setDisplayName] = useState("");
  const [key, setKey] = useState("");
  const [createClasses, setCreateClasses] = useState(true);
  const create = useMutation({
    mutationFn: () =>
      api<{ id: number; key: string; classes_created: string[] }>("/config/ppe-items", {
        method: "POST",
        json: { display_name: displayName, key: key.trim() || null, create_classes: createClasses },
      }),
    onSuccess: invalidate,
  });

  if (create.isSuccess) {
    const created = create.data.classes_created;
    return (
      <div className="grid gap-4">
        <Alert tone="ok">
          Added <b>{displayName.trim()}</b> ({create.data.key}).
          {created.length > 0 && ` Detection classes created: ${created.join(", ")}.`}
        </Alert>
        <p className="text-sm text-ink-2">
          The current model can&apos;t see this PPE yet. Annotate examples of both classes, then build a dataset and retrain.
          Until the new model is promoted, areas that require it won&apos;t raise violations for it.
        </p>
        <div className="flex justify-end">
          <button type="button" className="btn btn-ink" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    );
  }

  const name = displayName.trim() || "Name";
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
        <label htmlFor="ppe-display" className="label">Display name</label>
        <input
          id="ppe-display"
          className="input"
          required
          autoFocus
          maxLength={100}
          placeholder="e.g. Harness"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </div>
      <div>
        <label htmlFor="ppe-key" className="label">Key (optional)</label>
        <input
          id="ppe-key"
          className="input font-mono text-xs"
          maxLength={50}
          placeholder={displayName.trim() ? displayName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") : "harness"}
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <p className="mt-1.5 text-xs text-ink-3">Lowercase letters, numbers and underscores. Generated from the name if left empty.</p>
      </div>
      <Switch
        checked={createClasses}
        onChange={setCreateClasses}
        label={`Also create “${name}” and “No ${name}” detection classes`}
        description="Needed before anyone can annotate this PPE for training."
      />
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className="btn btn-ink" disabled={create.isPending || !displayName.trim()}>
          {create.isPending && <Spinner />} Add PPE type
        </button>
      </div>
    </form>
  );
}
