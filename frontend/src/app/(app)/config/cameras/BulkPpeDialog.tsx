"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";

import { PpeChipPicker } from "../_shared/PpeChips";
import { overviewKey, type PpeItemRef } from "../_shared/types";

type PpeAction = "add_ppe" | "remove_ppe" | "set_ppe";

const ACTIONS: Array<{ value: PpeAction; label: string; hint: string }> = [
  { value: "add_ppe", label: "Add", hint: "Each camera keeps its PPE and also requires these." },
  { value: "remove_ppe", label: "Remove", hint: "These stop being required; everything else stays." },
  { value: "set_ppe", label: "Replace", hint: "Each camera requires exactly these, nothing else." },
];

export function BulkPpeDialog({
  cameraIds,
  ppeItems,
  open,
  onClose,
  onDone,
}: {
  cameraIds: number[];
  ppeItems: PpeItemRef[];
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Change required PPE"
      description={`Applies to ${cameraIds.length} selected camera${cameraIds.length === 1 ? "" : "s"}.`}
      wide
    >
      {open && <BulkForm cameraIds={cameraIds} ppeItems={ppeItems} onCancel={onClose} onDone={onDone} />}
    </Dialog>
  );
}

function BulkForm({
  cameraIds,
  ppeItems,
  onCancel,
  onDone,
}: {
  cameraIds: number[];
  ppeItems: PpeItemRef[];
  onCancel: () => void;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [action, setAction] = useState<PpeAction>("add_ppe");
  const [ppe, setPpe] = useState<string[]>([]);
  const apply = useMutation({
    mutationFn: () => api("/config/cameras/bulk", { method: "POST", json: { camera_ids: cameraIds, action, ppe } }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: overviewKey });
      onDone();
    },
  });
  const hint = ACTIONS.find((a) => a.value === action)?.hint;

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        apply.mutate();
      }}
    >
      {apply.isError && <Alert tone="critical">{apply.error.message}</Alert>}
      <fieldset>
        <legend className="label">Change</legend>
        <div className="inline-flex rounded-md border border-line p-0.5" role="radiogroup">
          {ACTIONS.map((a) => (
            <button
              key={a.value}
              type="button"
              role="radio"
              aria-checked={action === a.value}
              onClick={() => setAction(a.value)}
              className={`h-8 rounded-sm px-3 text-xs font-bold transition ${
                action === a.value ? "bg-accent-50 text-accent-700" : "text-ink-2 hover:bg-surface-2"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-ink-3">{hint}</p>
      </fieldset>
      <PpeChipPicker items={ppeItems} value={ppe} onChange={setPpe} legend="PPE" />
      {action === "set_ppe" && ppe.length === 0 && (
        <Alert tone="warn">With nothing selected, these areas are checked for every enabled PPE type.</Alert>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn btn-ink" disabled={apply.isPending || (action !== "set_ppe" && ppe.length === 0)}>
          {apply.isPending && <Spinner />} Apply to {cameraIds.length}
        </button>
      </div>
    </form>
  );
}
