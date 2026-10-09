"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";

import { overviewKey, type PlantNode } from "../_shared/types";

export type NameDialogState =
  | { kind: "plant" }
  | { kind: "house"; plantId?: number }
  | { kind: "rename-house"; houseId: number; name: string }
  | null;

/** Add a plant, add a production house, or rename a production house. */
export function NameDialog({
  state,
  plants,
  onClose,
  onCreatedHouse,
}: {
  state: NameDialogState;
  plants: PlantNode[];
  onClose: () => void;
  onCreatedHouse?: (houseId: number) => void;
}) {
  const title =
    state?.kind === "plant" ? "Add plant" : state?.kind === "house" ? "Add production house" : "Rename production house";
  return (
    <Dialog open={!!state} onClose={onClose} title={title}>
      {state && (
        <NameForm
          key={JSON.stringify(state)}
          state={state}
          plants={plants}
          onDone={onClose}
          onCreatedHouse={onCreatedHouse}
        />
      )}
    </Dialog>
  );
}

function NameForm({
  state,
  plants,
  onDone,
  onCreatedHouse,
}: {
  state: NonNullable<NameDialogState>;
  plants: PlantNode[];
  onDone: () => void;
  onCreatedHouse?: (houseId: number) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(state.kind === "rename-house" ? state.name : "");
  const [plantId, setPlantId] = useState<number>(
    (state.kind === "house" && state.plantId) || plants[0]?.id || 0,
  );

  const save = useMutation({
    mutationFn: async () => {
      if (state.kind === "plant") return api("/config/plants", { method: "POST", json: { name } });
      if (state.kind === "house") {
        const house = await api<{ id: number }>("/config/production-houses", {
          method: "POST",
          json: { plant_id: plantId, name },
        });
        onCreatedHouse?.(house.id);
        return house;
      }
      return api(`/config/production-houses/${state.houseId}`, { method: "PATCH", json: { name } });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: overviewKey });
      onDone();
    },
  });

  const needsPlant = state.kind === "house";
  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {save.isError && <Alert tone="critical">{save.error.message}</Alert>}
      {needsPlant &&
        (plants.length ? (
          <div>
            <label htmlFor="house-plant" className="label">Plant</label>
            <select id="house-plant" className="input" value={plantId} onChange={(e) => setPlantId(Number(e.target.value))}>
              {plants.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <Alert tone="warn">Add a plant first.</Alert>
        ))}
      <div>
        <label htmlFor="name-input" className="label">Name</label>
        <input
          id="name-input"
          className="input"
          required
          autoFocus
          maxLength={100}
          placeholder={state.kind === "plant" ? "e.g. CHAKDOH" : "e.g. PP-25"}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {state.kind === "rename-house" && (
          <p className="mt-1.5 text-xs text-ink-3">
            Events already recorded keep the old name, so dashboard filters will list both.
          </p>
        )}
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className="btn btn-ink" disabled={save.isPending || !name.trim() || (needsPlant && !plantId)}>
          {save.isPending && <Spinner />} Save
        </button>
      </div>
    </form>
  );
}
