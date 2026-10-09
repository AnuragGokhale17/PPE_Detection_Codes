"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";

import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";

import { PpeChips } from "../_shared/PpeChips";
import { cameraStatus, overviewKey, type CameraRow, type CameraStatus, type PpeItemRef } from "../_shared/types";

const STATUS: Record<CameraStatus, { label: string; cls: string }> = {
  online: { label: "Online", cls: "pill-ok" },
  offline: { label: "Offline", cls: "pill-critical" },
  unreported: { label: "Not reported", cls: "pill-quiet" },
  disabled: { label: "Disabled", cls: "pill-quiet" },
};

export function CameraTable({
  cameras,
  ppeItems,
  selected,
  onSelectedChange,
  canCameras,
  canPpe,
  onEdit,
  onDelete,
  onBulkPpe,
}: {
  cameras: CameraRow[];
  ppeItems: PpeItemRef[];
  selected: Set<number>;
  onSelectedChange: (next: Set<number>) => void;
  canCameras: boolean;
  canPpe: boolean;
  onEdit: (camera: CameraRow) => void;
  onDelete: (camera: CameraRow) => void;
  onBulkPpe: () => void;
}) {
  const queryClient = useQueryClient();
  const toggleAll = cameras.length > 0 && cameras.every((c) => selected.has(c.id));
  const someSelected = cameras.some((c) => selected.has(c.id));
  const selectedIds = cameras.filter((c) => selected.has(c.id)).map((c) => c.id);

  const bulk = useMutation({
    mutationFn: (action: "enable" | "disable") =>
      api<{ updated: number }>("/config/cameras/bulk", { method: "POST", json: { camera_ids: selectedIds, action } }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: overviewKey });
      onSelectedChange(new Set());
    },
  });

  return (
    <div>
      {someSelected && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-accent-50 px-4 py-2.5">
          <span className="tabular mr-1 text-[13px] font-bold text-accent-700">{selectedIds.length} selected</span>
          {canCameras && (
            <>
              <button type="button" className="btn btn-sm" disabled={bulk.isPending} onClick={() => bulk.mutate("enable")}>
                Enable
              </button>
              <button type="button" className="btn btn-sm" disabled={bulk.isPending} onClick={() => bulk.mutate("disable")}>
                Disable
              </button>
            </>
          )}
          {(canPpe || canCameras) && (
            <button type="button" className="btn btn-sm" onClick={onBulkPpe}>
              Change required PPE
            </button>
          )}
          {bulk.isPending && <Spinner />}
          <button type="button" className="btn btn-quiet btn-sm ml-auto" onClick={() => onSelectedChange(new Set())}>
            Clear selection
          </button>
        </div>
      )}
      {bulk.isError && (
        <div className="p-3">
          <Alert tone="critical">{bulk.error.message}</Alert>
        </div>
      )}
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead className="border-b border-line bg-surface-2 text-xs text-ink-3">
            <tr>
              <th scope="col" className="w-10 px-4 py-2.5">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--accent-600)]"
                  aria-label="Select all cameras in this production house"
                  checked={toggleAll}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected && !toggleAll;
                  }}
                  onChange={(e) => onSelectedChange(new Set(e.target.checked ? cameras.map((c) => c.id) : []))}
                />
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium">Area</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Status</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Required PPE</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Stream</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {cameras.map((cam) => {
              const status = STATUS[cameraStatus(cam)];
              return (
                <tr key={cam.id} className={`border-b border-line align-top last:border-0 ${selected.has(cam.id) ? "bg-accent-50/50" : "hover:bg-surface-2"}`}>
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      className="size-4 accent-[var(--accent-600)]"
                      aria-label={`Select ${cam.area}`}
                      checked={selected.has(cam.id)}
                      onChange={(e) => {
                        const next = new Set(selected);
                        if (e.target.checked) next.add(cam.id);
                        else next.delete(cam.id);
                        onSelectedChange(next);
                      }}
                    />
                  </td>
                  <td className="px-3 py-3">
                    <p className="font-medium break-words text-ink">{cam.area}</p>
                    {cam.scale_up && <p className="text-[11px] text-ink-3">Upscaled low-resolution stream</p>}
                    {cam.notes && <p className="mt-0.5 line-clamp-2 text-xs text-ink-3">{cam.notes}</p>}
                  </td>
                  <td className="px-3 py-3">
                    <span className={`pill ${status.cls}`}>{status.label}</span>
                    {cam.enabled && cam.health?.last_checked && (
                      <p className="mt-1 text-[11px] text-ink-3">Checked {relativeTime(cam.health.last_checked)}</p>
                    )}
                  </td>
                  <td className="min-w-[15rem] px-3 py-3">
                    <PpeChips keys={cam.ppe} items={ppeItems} />
                  </td>
                  <td className="max-w-[16rem] px-3 py-3">
                    <p className="truncate font-mono text-xs text-ink-2" title={cam.stream_url}>
                      {cam.stream_url}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1.5">
                      <button type="button" className="btn btn-sm" onClick={() => onEdit(cam)} aria-label={`Edit ${cam.area}`}>
                        <Pencil className="size-3.5" aria-hidden /> {canCameras ? "Edit" : "Edit PPE"}
                      </button>
                      {canCameras && (
                        <button
                          type="button"
                          className="btn btn-quiet btn-sm text-critical"
                          aria-label={`Delete ${cam.area}`}
                          onClick={() => onDelete(cam)}
                        >
                          <Trash2 className="size-3.5" aria-hidden />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
