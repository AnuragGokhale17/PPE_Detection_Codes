"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, ImagePlus, PenTool, Upload } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { Forbidden, PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/components/ui/Pagination";
import { PageLoading, Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";
import { can, canAny, PERMISSIONS, useMe } from "@/lib/auth";
import { formatNumber, relativeTime } from "@/lib/format";

export interface SampleSummary {
  id: number;
  status: "draft" | "submitted" | "approved" | "rejected";
  source: "review" | "upload" | "snapshot";
  production_house: string | null;
  area: string | null;
  label_count: number;
  class_ids: number[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
  reject_reason: string | null;
}

interface Stats {
  status_counts: Record<string, number>;
  background_images: number;
  classes: Array<{
    class_id: number;
    name: string;
    is_violation: boolean;
    enabled: boolean;
    approved_instances: number;
    approved_images: number;
    pending_instances: number;
  }>;
}

const TABS = [
  { id: "draft", label: "Drafts" },
  { id: "submitted", label: "Waiting for QA" },
  { id: "rejected", label: "Sent back" },
  { id: "approved", label: "In training pool" },
  { id: "all", label: "All" },
] as const;
const PAGE_SIZE = 24;
// Below this many boxes a class is usually under-represented for YOLO fine-tuning
const LOW_INSTANCES = 50;

export function StatusPill({ status }: { status: SampleSummary["status"] }) {
  const map = {
    draft: ["pill-quiet", "Draft"],
    submitted: ["pill-info", "Waiting for QA"],
    approved: ["pill-ok", "In training pool"],
    rejected: ["pill-warn", "Sent back"],
  } as const;
  const [cls, label] = map[status];
  return <span className={`pill ${cls}`}>{label}</span>;
}

export function AnnotateHome() {
  const { data: me } = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const allowed = canAny(me, [PERMISSIONS.annotationsCreate, PERMISSIONS.annotationsApprove]);
  const canCreate = can(me, PERMISSIONS.annotationsCreate);
  const isApprover = can(me, PERMISSIONS.annotationsApprove);
  const status = params.get("status") ?? (isApprover && !canCreate ? "submitted" : "draft");
  const page = Number(params.get("page") ?? 0);
  const classFilter = params.get("class");
  const mine = params.get("mine") === "1";

  const setParam = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v == null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`${pathname}?${next}`);
  };

  const stats = useQuery({ queryKey: ["samples", "stats"], queryFn: () => api<Stats>("/samples/stats"), enabled: allowed });
  const list = useQuery({
    queryKey: ["samples", "list", status, page, classFilter, mine],
    queryFn: () => {
      const q = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (status !== "all") q.set("status", status);
      if (classFilter) q.set("class_id", classFilter);
      if (mine) q.set("mine", "true");
      return api<{ total: number; items: SampleSummary[] }>(`/samples?${q}`);
    },
    enabled: allowed,
    placeholderData: keepPreviousData,
  });
  const [uploading, setUploading] = useState(false);
  const [snapshotOpen, setSnapshotOpen] = useState(false);

  const classNames = useMemo(() => new Map((stats.data?.classes ?? []).map((c) => [c.class_id, c.name])), [stats.data]);

  if (!allowed) return <Forbidden />;

  return (
    <>
      <PageHeader
        eyebrow="Model quality"
        title="Annotate"
        description="Label frames the model missed or got wrong, especially classes with few examples. Approved images form the training pool (YOLO images + labels)."
        actions={
          canCreate ? (
            <>
              <button type="button" className="btn" onClick={() => setSnapshotOpen(true)}>
                <Camera className="size-4" aria-hidden /> Capture from camera
              </button>
              <button type="button" className="btn btn-primary" onClick={() => setUploading(true)}>
                <Upload className="size-4" aria-hidden /> Upload images
              </button>
            </>
          ) : undefined
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div role="tablist" aria-label="Sample status" className="flex flex-wrap rounded-md border border-line bg-surface p-0.5">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  type="button"
                  aria-selected={status === t.id}
                  onClick={() => setParam({ status: t.id, page: null })}
                  className={`flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 text-[13px] font-medium ${
                    status === t.id ? "bg-accent-50 text-accent-700" : "text-ink-2 hover:bg-surface-3"
                  }`}
                >
                  {t.label}
                  {t.id !== "all" && stats.data && (
                    <span className="tabular text-xs text-ink-3">{formatNumber(stats.data.status_counts[t.id] ?? 0)}</span>
                  )}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-4">
              {classFilter && (
                <button type="button" className="pill pill-info" onClick={() => setParam({ class: null, page: null })}>
                  {classNames.get(Number(classFilter))} ✕
                </button>
              )}
              <Switch checked={mine} onChange={(v) => setParam({ mine: v ? "1" : null, page: null })} label="Only mine" />
            </div>
          </div>

          {list.isPending ? (
            <PageLoading />
          ) : list.isError ? (
            <Alert tone="critical">{list.error.message}</Alert>
          ) : list.data.items.length === 0 ? (
            <div className="panel">
              <EmptyState icon={PenTool} title="No images here">
                {status === "draft" && canCreate
                  ? "Upload photos, capture a frame from a camera, or save corrected boxes from the review screen."
                  : "Nothing matches these filters."}
              </EmptyState>
            </div>
          ) : (
            <>
              <ul className={`grid gap-3 sm:grid-cols-2 lg:grid-cols-3 ${list.isPlaceholderData ? "opacity-60" : ""}`}>
                {list.data.items.map((s) => (
                  <li key={s.id}>
                    <Link
                      href={`/annotate/${s.id}?status=${s.status}`}
                      className="panel block overflow-hidden transition hover:shadow-md focus-visible:ring-3 focus-visible:ring-accent-200 focus-visible:outline-none"
                    >
                      <div className="aspect-video bg-surface-sunken">
                        {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                        <img src={`/api/samples/${s.id}/image`} alt="" loading="lazy" className="h-full w-full object-cover" />
                      </div>
                      <div className="grid gap-1.5 p-3">
                        <p className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-bold">{s.production_house ?? "Uploaded image"}</span>
                          <StatusPill status={s.status} />
                        </p>
                        <p className="truncate text-xs text-ink-2">{s.area ?? `#${s.id}`}</p>
                        <p className="text-xs text-ink-3">
                          {s.label_count} box{s.label_count === 1 ? "" : "es"} · {s.source === "review" ? "from review" : s.source} · {relativeTime(s.updated_at)}
                        </p>
                        {s.status === "rejected" && s.reject_reason && <p className="text-xs text-warn">“{s.reject_reason}”</p>}
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
              <div className="mt-4">
                <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={(p) => setParam({ page: String(p) })} />
              </div>
            </>
          )}
        </div>

        <ClassBalance stats={stats.data} onPick={(id) => setParam({ class: String(id), status: "all", page: null })} />
      </div>

      <UploadDialog open={uploading} onClose={() => setUploading(false)} />
      <SnapshotDialog open={snapshotOpen} onClose={() => setSnapshotOpen(false)} />
    </>
  );
}

function ClassBalance({ stats, onPick }: { stats?: Stats; onPick: (classId: number) => void }) {
  if (!stats) return <section className="panel p-5"><PageLoading /></section>;
  const rows = stats.classes.filter((c) => c.enabled);
  const max = Math.max(1, ...rows.map((c) => c.approved_instances));
  return (
    <section className="panel content-start p-5">
      <h2 className="rule-head">Class balance in the training pool</h2>
      <p className="mt-1 mb-4 text-xs text-ink-3">
        Approved boxes per class. Classes under {LOW_INSTANCES} need more examples; pending boxes are shown in brackets.
      </p>
      <ul className="grid gap-2">
        {[...rows]
          .sort((a, b) => a.approved_instances - b.approved_instances)
          .map((c) => {
            const low = c.approved_instances < LOW_INSTANCES;
            return (
              <li key={c.class_id}>
                <button type="button" className="grid w-full gap-1 rounded-sm px-1 py-0.5 text-left hover:bg-surface-2" onClick={() => onPick(c.class_id)}>
                  <span className="flex items-baseline justify-between gap-2 text-[13px]">
                    <span className="truncate text-ink-2">
                      {c.name} {low && <span className="pill pill-warn ml-1">Needs more</span>}
                    </span>
                    <span className="tabular shrink-0 font-medium">
                      {formatNumber(c.approved_instances)}
                      {c.pending_instances > 0 && <span className="font-normal text-ink-3"> (+{formatNumber(c.pending_instances)})</span>}
                    </span>
                  </span>
                  <span className="h-1.5 rounded-full bg-surface-3" aria-hidden>
                    <span className="block h-full rounded-r bg-data" style={{ width: `${Math.max(1, (c.approved_instances / max) * 100)}%` }} />
                  </span>
                </button>
              </li>
            );
          })}
      </ul>
      <p className="mt-4 text-xs text-ink-3">
        {formatNumber(stats.background_images)} background images (no PPE in frame) help cut false alarms on machinery.
      </p>
    </section>
  );
}

function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Upload images" description="JPEG or PNG, up to 20 MB each and 100 per batch. They're added as drafts for you to label." wide>
      {open && <UploadForm onDone={onClose} />}
    </Dialog>
  );
}

function UploadForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [house, setHouse] = useState("");
  const [area, setArea] = useState("");
  const [dragging, setDragging] = useState(false);
  const upload = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      if (house.trim()) form.append("production_house", house.trim());
      if (area.trim()) form.append("area", area.trim());
      return api<{ created: number[]; skipped: Array<{ file: string; reason: string }> }>("/samples/upload", { method: "POST", body: form });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["samples"] }),
  });

  if (upload.isSuccess) {
    const { created, skipped } = upload.data;
    return (
      <div className="grid gap-4">
        <Alert tone={created.length ? "ok" : "warn"}>
          {created.length} image{created.length === 1 ? "" : "s"} added as drafts.
        </Alert>
        {skipped.length > 0 && (
          <ul className="grid gap-1 text-xs text-ink-2">
            {skipped.map((s) => (
              <li key={s.file}>
                <span className="font-medium">{s.file}</span>: {s.reason}
              </li>
            ))}
          </ul>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onDone}>Close</button>
          {created.length > 0 && (
            <Link href={`/annotate/${created[0]}?status=draft`} className="btn btn-ink" onClick={onDone}>
              Start labelling
            </Link>
          )}
        </div>
      </div>
    );
  }

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        upload.mutate();
      }}
    >
      {upload.isError && <Alert tone="critical">{upload.error.message}</Alert>}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          setFiles(Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/")));
        }}
        className={`flex flex-col items-center gap-2 rounded-md border border-dashed px-4 py-8 text-center ${dragging ? "border-accent-600 bg-accent-50" : "border-line-strong"}`}
      >
        <ImagePlus className="size-6 text-ink-3" aria-hidden />
        <p className="text-sm text-ink-2">Drop images here, or</p>
        <button type="button" className="btn btn-sm" onClick={() => input.current?.click()}>Choose files</button>
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/bmp"
          multiple
          className="sr-only"
          aria-label="Choose image files"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        {files.length > 0 && <p className="text-xs font-medium text-ink">{files.length} selected</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="up-house" className="label">Production house (optional)</label>
          <input id="up-house" className="input" value={house} onChange={(e) => setHouse(e.target.value)} />
        </div>
        <div>
          <label htmlFor="up-area" className="label">Area (optional)</label>
          <input id="up-area" className="input" value={area} onChange={(e) => setArea(e.target.value)} />
        </div>
      </div>
      <p className="text-xs text-ink-3">The location keeps train and validation images balanced across areas.</p>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onDone}>Cancel</button>
        <button type="submit" className="btn btn-ink" disabled={!files.length || upload.isPending}>
          {upload.isPending && <Spinner />} Upload {files.length || ""}
        </button>
      </div>
    </form>
  );
}

interface Overview {
  plants: Array<{ name: string; production_houses: Array<{ name: string; cameras: Array<{ id: number; area: string; enabled: boolean; health: { online: boolean | null } | null }> }> }>;
}

function SnapshotDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Capture from camera" description="Grabs the current frame from a camera so you can label it. Useful for areas and classes the model rarely sees.">
      {open && <SnapshotForm onDone={onClose} />}
    </Dialog>
  );
}

function SnapshotForm({ onDone }: { onDone: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["config", "overview"], queryFn: () => api<Overview>("/config/overview") });
  const [cameraId, setCameraId] = useState("");
  const capture = useMutation({
    mutationFn: () => api<{ id: number }>("/samples/snapshot", { method: "POST", json: { camera_id: Number(cameraId) } }),
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ["samples"] });
      onDone();
      router.push(`/annotate/${res.id}?status=draft`);
    },
  });

  if (overview.isPending) return <PageLoading label="Loading cameras" />;
  if (overview.isError) return <Alert tone="critical">{overview.error.message}</Alert>;
  const houses = overview.data.plants.flatMap((p) => p.production_houses).filter((h) => h.cameras.length);

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        capture.mutate();
      }}
    >
      {capture.isError && <Alert tone="critical">{capture.error.message}</Alert>}
      {houses.length === 0 ? (
        <Alert tone="info">No cameras are configured yet.</Alert>
      ) : (
        <div>
          <label htmlFor="snap-camera" className="label">Camera</label>
          <select id="snap-camera" className="input" required value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
            <option value="" disabled>
              Choose an area
            </option>
            {houses.map((h) => (
              <optgroup key={h.name} label={h.name}>
                {h.cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.area}
                    {c.health?.online === false ? " (offline)" : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onDone}>Cancel</button>
        <button type="submit" className="btn btn-ink" disabled={!cameraId || capture.isPending}>
          {capture.isPending ? <Spinner /> : <Camera className="size-4" aria-hidden />} {capture.isPending ? "Connecting…" : "Capture frame"}
        </button>
      </div>
    </form>
  );
}
