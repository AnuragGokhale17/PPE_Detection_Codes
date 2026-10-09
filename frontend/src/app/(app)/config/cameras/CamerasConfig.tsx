"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera as CameraIcon, Download, Plus, Search, Upload } from "lucide-react";
import { useMemo, useState } from "react";

import { Forbidden, PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageLoading } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";
import { formatNumber, relativeTime } from "@/lib/format";

import { ConfirmDialog } from "../_shared/ConfirmDialog";
import { cameraStatus, overviewKey, type CameraRow, type ConfigOverview, type HouseNode, type PlantNode } from "../_shared/types";
import { BulkPpeDialog } from "./BulkPpeDialog";
import { CameraDialog, type CameraDialogState } from "./CameraDialog";
import { CameraTable } from "./CameraTable";
import { NameDialog, type NameDialogState } from "./HouseDialogs";
import { HouseList, matchHouses } from "./HouseList";
import { ExportDialog, ImportDialog } from "./ImportExportDialogs";

export function CamerasConfig() {
  const { data: me } = useMe();
  const canCameras = can(me, PERMISSIONS.configCameras);
  const canPpe = can(me, PERMISSIONS.configPpe);
  const allowed = canCameras || canPpe;
  const queryClient = useQueryClient();
  const overview = useQuery({
    queryKey: overviewKey,
    queryFn: () => api<ConfigOverview>("/config/overview"),
    enabled: allowed,
  });

  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selection, setSelection] = useState<{ houseId: number | null; ids: Set<number> }>({ houseId: null, ids: new Set() });
  const [cameraDialog, setCameraDialog] = useState<CameraDialogState>(null);
  const [nameDialog, setNameDialog] = useState<NameDialogState>(null);
  const [deletingCamera, setDeletingCamera] = useState<CameraRow | null>(null);
  const [deletingHouse, setDeletingHouse] = useState<HouseNode | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const plants: PlantNode[] = useMemo(() => overview.data?.plants ?? [], [overview.data]);
  const matches = useMemo(() => matchHouses(plants, query), [plants, query]);
  const houses = useMemo(
    () => plants.flatMap((p) => p.production_houses.map((h) => ({ house: h, plant: p }))),
    [plants],
  );

  if (!allowed) return <Forbidden />;
  if (overview.isPending) return <PageLoading />;
  if (overview.isError) return <Alert tone="critical">{overview.error.message}</Alert>;

  const data = overview.data;
  const visible = houses.filter(({ house }) => matches.has(house.id));
  const current = visible.find(({ house }) => house.id === selectedId) ?? visible[0] ?? null;
  const match = current ? matches.get(current.house.id) : undefined;
  const cameras = current
    ? match?.areaMatches != null
      ? current.house.cameras.filter((c) => c.area.toLowerCase().includes(query.trim().toLowerCase()))
      : current.house.cameras
    : [];
  const selectedIds = selection.houseId === current?.house.id ? selection.ids : new Set<number>();

  const all = houses.flatMap(({ house }) => house.cameras);
  const enabledCount = all.filter((c) => c.enabled).length;
  const offlineCount = all.filter((c) => cameraStatus(c) === "offline").length;

  const selectHouse = (id: number) => {
    setSelectedId(id);
    setSelection({ houseId: id, ids: new Set() });
  };

  return (
    <>
      <PageHeader
        eyebrow="Configuration"
        title="Cameras & areas"
        description="Each camera watches one area and checks it for the PPE that area requires. Changes reach live detection within about 30 seconds, with no restart."
        actions={
          canCameras && (
            <>
              <button type="button" className="btn" onClick={() => setImportOpen(true)}>
                <Upload className="size-4" aria-hidden /> Import
              </button>
              <button type="button" className="btn" onClick={() => setExportOpen(true)}>
                <Download className="size-4" aria-hidden /> Export
              </button>
              <button type="button" className="btn" onClick={() => setNameDialog({ kind: "plant" })}>
                <Plus className="size-4" aria-hidden /> Add plant
              </button>
            </>
          )
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-ink-2">
        <span>
          <span className="tabular font-bold text-ink">{formatNumber(all.length)}</span> cameras ·{" "}
          <span className="tabular">{formatNumber(enabledCount)}</span> enabled
        </span>
        {offlineCount > 0 && <span className="pill pill-critical tabular">{offlineCount} offline</span>}
        <span className="text-xs text-ink-3">
          Configuration version {data.config_version}
          {data.updated_by ? ` · last changed by ${data.updated_by}` : ""} · {relativeTime(data.updated_at)}
        </span>
      </div>

      {plants.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={CameraIcon}
            title="No cameras configured yet"
            action={
              canCameras && (
                <div className="flex flex-wrap justify-center gap-2">
                  <button type="button" className="btn btn-ink" onClick={() => setImportOpen(true)}>
                    Import a camera list
                  </button>
                  <button type="button" className="btn" onClick={() => setNameDialog({ kind: "plant" })}>
                    Add a plant
                  </button>
                </div>
              )
            }
          >
            Import the existing camera_list JSON files, or add a plant and its production houses by hand.
          </EmptyState>
        </div>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <aside className="panel p-3 lg:sticky lg:top-6">
            <label className="relative block">
              <span className="sr-only">Search production houses and areas</span>
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
              <input
                className="input h-9 pl-9"
                placeholder="Search houses or areas"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            {canCameras && (
              <button
                type="button"
                className="btn btn-quiet btn-sm mt-2 w-full justify-start"
                onClick={() => setNameDialog({ kind: "house", plantId: current?.plant.id })}
              >
                <Plus className="size-3.5" aria-hidden /> Add production house
              </button>
            )}
            <div className="mt-2 max-h-72 overflow-y-auto pr-1 lg:max-h-[calc(100vh-14rem)]">
              <HouseList plants={plants} matches={matches} selectedId={current?.house.id ?? null} onSelect={selectHouse} />
            </div>
          </aside>

          <section className="panel min-w-0" aria-label={current ? `Cameras in ${current.house.name}` : "Cameras"}>
            {current ? (
              <>
                <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line p-4">
                  <div className="min-w-0">
                    <p className="eyebrow">{current.plant.name}</p>
                    <h2 className="text-lg font-bold break-words">{current.house.name}</h2>
                    <p className="tabular text-xs text-ink-3">
                      {current.house.cameras.length} camera{current.house.cameras.length === 1 ? "" : "s"}
                      {match?.areaMatches != null && ` · showing ${cameras.length} matching “${query.trim()}”`}
                    </p>
                  </div>
                  {canCameras && (
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn btn-quiet btn-sm"
                        onClick={() => setNameDialog({ kind: "rename-house", houseId: current.house.id, name: current.house.name })}
                      >
                        Rename
                      </button>
                      <button type="button" className="btn btn-quiet btn-sm text-critical" onClick={() => setDeletingHouse(current.house)}>
                        Delete
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => setCameraDialog({ mode: "create", houseId: current.house.id })}
                      >
                        <Plus className="size-3.5" aria-hidden /> Add camera
                      </button>
                    </div>
                  )}
                </div>
                {cameras.length ? (
                  <CameraTable
                    cameras={cameras}
                    ppeItems={data.ppe_items}
                    selected={selectedIds}
                    onSelectedChange={(ids) => setSelection({ houseId: current.house.id, ids })}
                    canCameras={canCameras}
                    canPpe={canPpe}
                    onEdit={(camera) => setCameraDialog({ mode: "edit", camera })}
                    onDelete={setDeletingCamera}
                    onBulkPpe={() => setBulkOpen(true)}
                  />
                ) : (
                  <EmptyState icon={CameraIcon} title="No cameras in this production house">
                    {canCameras ? "Add a camera for each area that should be monitored." : null}
                  </EmptyState>
                )}
              </>
            ) : (
              <EmptyState icon={Search} title="Nothing matches your search" />
            )}
          </section>
        </div>
      )}

      <CameraDialog
        state={cameraDialog}
        plants={plants}
        ppeItems={data.ppe_items}
        canEditCamera={canCameras}
        onClose={() => setCameraDialog(null)}
      />
      <NameDialog state={nameDialog} plants={plants} onClose={() => setNameDialog(null)} onCreatedHouse={selectHouse} />
      <BulkPpeDialog
        open={bulkOpen}
        cameraIds={[...selectedIds]}
        ppeItems={data.ppe_items}
        onClose={() => setBulkOpen(false)}
        onDone={() => {
          setBulkOpen(false);
          setSelection({ houseId: current?.house.id ?? null, ids: new Set() });
        }}
      />
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <ExportDialog open={exportOpen} onClose={() => setExportOpen(false)} />
      <ConfirmDialog
        open={!!deletingCamera}
        title="Delete camera?"
        description={deletingCamera ? `${current?.house.name ?? ""} / ${deletingCamera.area}` : undefined}
        body="Live detection stops for this area within about 30 seconds. Violations already recorded are kept. To pause monitoring but keep the settings, disable the camera instead."
        confirmLabel="Delete camera"
        onConfirm={async () => {
          await api(`/config/cameras/${deletingCamera?.id}`, { method: "DELETE" });
          await queryClient.invalidateQueries({ queryKey: overviewKey });
        }}
        onClose={() => setDeletingCamera(null)}
      />
      <ConfirmDialog
        open={!!deletingHouse}
        title="Delete production house?"
        description={deletingHouse?.name}
        body="Its alert recipients are removed too. A production house can only be deleted once it has no cameras."
        confirmLabel="Delete production house"
        onConfirm={async () => {
          await api(`/config/production-houses/${deletingHouse?.id}`, { method: "DELETE" });
          setSelectedId(null);
          await queryClient.invalidateQueries({ queryKey: overviewKey });
        }}
        onClose={() => setDeletingHouse(null)}
      />
    </>
  );
}
