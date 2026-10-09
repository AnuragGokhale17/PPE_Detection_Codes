"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";

import { PpeChipPicker } from "../_shared/PpeChips";
import { overviewKey, type CameraRow, type PlantNode, type PpeItemRef } from "../_shared/types";
import { StreamTest } from "./StreamTest";

export type CameraDialogState =
  | { mode: "create"; houseId: number }
  | { mode: "edit"; camera: CameraRow }
  | null;

export function CameraDialog({
  state,
  plants,
  ppeItems,
  canEditCamera,
  onClose,
}: {
  state: CameraDialogState;
  plants: PlantNode[];
  ppeItems: PpeItemRef[];
  /** false = PPE-only editor (config.ppe without config.cameras) */
  canEditCamera: boolean;
  onClose: () => void;
}) {
  const editing = state?.mode === "edit" ? state.camera : null;
  return (
    <Dialog
      open={!!state}
      onClose={onClose}
      title={editing ? `Edit ${editing.area}` : "Add camera"}
      description={
        editing
          ? canEditCamera
            ? "Changes reach live detection within about 30 seconds."
            : "You can change the PPE this area requires. Other settings need the camera permission."
          : "One camera monitors one area. Detection starts within about 30 seconds of saving."
      }
      wide
    >
      {state && (
        <CameraForm
          key={editing ? `edit-${editing.id}` : `new-${state.mode === "create" ? state.houseId : ""}`}
          state={state}
          plants={plants}
          ppeItems={ppeItems}
          canEditCamera={canEditCamera}
          onDone={onClose}
        />
      )}
    </Dialog>
  );
}

function CameraForm({
  state,
  plants,
  ppeItems,
  canEditCamera,
  onDone,
}: {
  state: NonNullable<CameraDialogState>;
  plants: PlantNode[];
  ppeItems: PpeItemRef[];
  canEditCamera: boolean;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const camera = state.mode === "edit" ? state.camera : null;
  const [houseId, setHouseId] = useState<number>(camera?.production_house_id ?? (state.mode === "create" ? state.houseId : 0));
  const [area, setArea] = useState(camera?.area ?? "");
  const [streamUrl, setStreamUrl] = useState(camera?.stream_url ?? "");
  const [enabled, setEnabled] = useState(camera?.enabled ?? true);
  const [scaleUp, setScaleUp] = useState(camera?.scale_up ?? false);
  const [notes, setNotes] = useState(camera?.notes ?? "");
  const [ppe, setPpe] = useState<string[]>(camera?.ppe ?? ppeItems.filter((i) => i.enabled).map((i) => i.key));

  const ppeOnly = !canEditCamera;
  const save = useMutation({
    mutationFn: () => {
      if (ppeOnly && camera) return api(`/config/cameras/${camera.id}`, { method: "PATCH", json: { ppe } });
      const body = {
        production_house_id: houseId,
        area: area.trim(),
        stream_url: streamUrl.trim(),
        enabled,
        scale_up: scaleUp,
        notes: notes.trim() || null,
        ppe,
      };
      return camera
        ? api(`/config/cameras/${camera.id}`, { method: "PATCH", json: body })
        : api("/config/cameras", { method: "POST", json: body });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: overviewKey });
      onDone();
    },
  });

  const masked = streamUrl.includes("••••");
  const invalid = !ppeOnly && (!area.trim() || streamUrl.trim().length < 8 || !houseId);

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {save.isError && <Alert tone="critical">{save.error.message}</Alert>}

      {ppeOnly && camera ? (
        <dl className="grid gap-x-4 gap-y-1 rounded-md border border-line bg-surface-2 px-3 py-2.5 text-[13px] sm:grid-cols-[8rem_1fr]">
          <dt className="text-ink-3">Area</dt>
          <dd className="font-medium">{camera.area}</dd>
          <dt className="text-ink-3">Stream</dt>
          <dd className="font-mono text-xs break-all text-ink-2">{camera.stream_url}</dd>
          <dt className="text-ink-3">Status</dt>
          <dd>{camera.enabled ? "Enabled" : "Disabled"}</dd>
        </dl>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="cam-house" className="label">Production house</label>
              <select id="cam-house" className="input" value={houseId} onChange={(e) => setHouseId(Number(e.target.value))}>
                {plants.map((plant) => (
                  <optgroup key={plant.id} label={plant.name}>
                    {plant.production_houses.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="cam-area" className="label">Area name</label>
              <input
                id="cam-area"
                className="input"
                required
                maxLength={150}
                placeholder="e.g. MIXING_AREA_FIRST_FLOOR"
                value={area}
                onChange={(e) => setArea(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label htmlFor="cam-url" className="label">Stream address</label>
            <input
              id="cam-url"
              className="input font-mono text-xs"
              required
              spellCheck={false}
              autoComplete="off"
              placeholder="rtsp://user:password@10.0.34.23:554/profile3/media.smp"
              value={streamUrl}
              onChange={(e) => setStreamUrl(e.target.value)}
            />
            <p className="mt-1.5 text-xs text-ink-3">
              {masked
                ? "The saved password is hidden. Leave •••• in place to keep it, or type the full address to change it."
                : "RTSP address including the camera's username and password."}
            </p>
          </div>
          <StreamTest streamUrl={streamUrl} cameraId={camera?.id} />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Switch checked={enabled} onChange={setEnabled} label="Enabled" description="Disabled cameras are not monitored or counted." />
            <Switch
              checked={scaleUp}
              onChange={setScaleUp}
              label="Low-resolution stream"
              description="Upscale the frame before detection."
            />
          </div>
        </>
      )}

      <PpeChipPicker
        items={ppeItems}
        value={ppe}
        onChange={setPpe}
        hint={
          ppe.length === 0
            ? "No PPE selected: the area is checked for every enabled PPE type."
            : "Only these PPE types raise violations in this area."
        }
      />

      {!ppeOnly && (
        <div>
          <label htmlFor="cam-notes" className="label">Notes</label>
          <textarea
            id="cam-notes"
            className="input h-auto min-h-16 py-2"
            maxLength={2000}
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className="btn btn-ink" disabled={save.isPending || invalid}>
          {save.isPending && <Spinner />} {camera ? "Save camera" : "Add camera"}
        </button>
      </div>
    </form>
  );
}
