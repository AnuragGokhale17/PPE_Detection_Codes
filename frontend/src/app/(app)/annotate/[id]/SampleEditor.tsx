"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, Save, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { use, useEffect, useState } from "react";

import { Annotator } from "@/components/annotator/Annotator";
import { sameLabels, toBox, toLabel, type Box, type ClassInfo, type Label } from "@/components/annotator/types";
import { useBoxHistory } from "@/components/annotator/useBoxHistory";
import { Forbidden } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { PageLoading, Spinner } from "@/components/ui/Spinner";
import { api, ApiError } from "@/lib/api";
import { can, canAny, PERMISSIONS, useMe } from "@/lib/auth";
import { useClasses } from "@/lib/classes";
import { formatDateTime } from "@/lib/format";

import { StatusPill, type SampleSummary } from "../AnnotateHome";

interface SampleDetail extends SampleSummary {
  width: number;
  height: number;
  ppes_id: number | null;
  labels: Label[];
  notes: string | null;
  approved_by: string | null;
  approved_at: string | null;
  next_id: number | null;
  prev_id: number | null;
}

export function SampleEditorPage({ idPromise }: { idPromise: Promise<string> }) {
  const id = use(idPromise);
  const params = useSearchParams();
  const status = params.get("status");
  const { data: me } = useMe();
  const allowed = canAny(me, [PERMISSIONS.annotationsCreate, PERMISSIONS.annotationsApprove]);
  const sample = useQuery({
    queryKey: ["samples", "detail", id, status],
    queryFn: () => api<SampleDetail>(`/samples/${id}${status && status !== "all" ? `?status=${status}` : ""}`),
    enabled: allowed,
  });
  const classes = useClasses();

  if (!allowed) return <Forbidden />;
  if (sample.isPending || classes.isPending) return <PageLoading label="Loading image" />;
  if (sample.isError) return <Alert tone="critical">{sample.error.message}</Alert>;
  if (classes.isError) return <Alert tone="critical">{classes.error.message}</Alert>;
  return (
    <Editor
      key={`${sample.data.id}-${sample.data.updated_at}`}
      sample={sample.data}
      classes={classes.data}
      queue={status ?? sample.data.status}
      canCreate={can(me, PERMISSIONS.annotationsCreate)}
      canApprove={can(me, PERMISSIONS.annotationsApprove)}
      isOwner={sample.data.created_by === me?.email}
    />
  );
}

function Editor({
  sample,
  classes,
  queue,
  canCreate,
  canApprove,
  isOwner,
}: {
  sample: SampleDetail;
  classes: ClassInfo[];
  queue: string;
  canCreate: boolean;
  canApprove: boolean;
  isOwner: boolean;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState<Box[]>(() => sample.labels.map(toBox));
  const history = useBoxHistory(saved);
  const [suggestions, setSuggestions] = useState<Box[]>([]);
  const [activeClass, setActiveClass] = useState(() => sample.labels[0]?.class_id ?? classes.find((c) => c.enabled)?.class_id ?? 0);
  const [rejecting, setRejecting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "critical" | "info"; text: string } | null>(null);

  const editable = canApprove || (canCreate && sample.status !== "approved");
  const dirty = !sameLabels(history.boxes, saved);
  const qs = queue && queue !== "all" ? `?status=${queue}` : "";

  // Don't lose work on refresh or tab close
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["samples"] });

  const save = useMutation({
    mutationFn: () => api<{ labels: Label[] }>(`/samples/${sample.id}/labels`, { method: "PUT", json: { labels: history.boxes.map(toLabel) } }),
    onSuccess: () => {
      setSaved(history.boxes);
      setMessage({ tone: "ok", text: "Saved." });
    },
    onError: (e) => setMessage({ tone: "critical", text: e.message }),
  });

  const transition = useMutation({
    mutationFn: async (action: "submit" | "approve") => {
      if (dirty) await save.mutateAsync();
      return api(`/samples/${sample.id}/${action}`, { method: "POST" });
    },
    onSuccess: async (_, action) => {
      await refresh();
      go(sample.next_id, action === "approve" ? "Approved into the training pool." : "Sent for QA.");
    },
    onError: (e) => setMessage({ tone: "critical", text: e.message }),
  });

  const suggest = useMutation({
    mutationFn: () => api<{ labels: Label[] }>(`/samples/${sample.id}/suggest`, { method: "POST" }),
    onSuccess: (res) => {
      // Offer what the model sees that isn't already boxed
      const fresh = res.labels.map(toBox).filter((s) => !history.boxes.some((b) => iou(b, s) > 0.5));
      setSuggestions(fresh);
      setMessage({ tone: "info", text: fresh.length ? `${fresh.length} suggestion${fresh.length === 1 ? "" : "s"} from the active model. Click one to add it.` : "The model found nothing new in this image." });
    },
    onError: (e) => setMessage({ tone: e instanceof ApiError && e.status === 501 ? "info" : "critical", text: e.message }),
  });

  function go(id: number | null, note?: string) {
    if (note) setMessage({ tone: "ok", text: note });
    router.push(id ? `/annotate/${id}${qs}` : `/annotate${qs}`);
  }

  // Ctrl+S saves
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (editable && dirty && !save.isPending) save.mutate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editable, dirty, save]);

  const accept = (s: Box) => {
    setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    history.commit((prev) => [...prev, s]);
  };

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/annotate${qs}`} className="btn btn-quiet btn-sm -ml-3 mb-1">
            <ArrowLeft className="size-4" aria-hidden /> All images
          </Link>
          <h1 className="flex flex-wrap items-center gap-2 text-xl font-bold tracking-tight">
            {sample.production_house ? `${sample.production_house} · ${sample.area ?? ""}` : `Image #${sample.id}`}
            <StatusPill status={sample.status} />
            {dirty && <span className="pill pill-warn">Unsaved changes</span>}
          </h1>
          <p className="mt-1 text-xs text-ink-3">
            #{sample.id} · {sample.source === "review" ? `from review of event #${sample.ppes_id}` : sample.source} · added by {sample.created_by ?? "unknown"}
            {sample.approved_by && ` · approved by ${sample.approved_by} ${formatDateTime(sample.approved_at)}`}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" className="btn btn-sm" disabled={!sample.prev_id} onClick={() => go(sample.prev_id)} aria-label="Previous image">
            <ChevronLeft className="size-4" aria-hidden />
          </button>
          <button type="button" className="btn btn-sm" disabled={!sample.next_id} onClick={() => go(sample.next_id)} aria-label="Next image">
            <ChevronRight className="size-4" aria-hidden />
          </button>
        </div>
      </div>

      {sample.status === "rejected" && sample.reject_reason && (
        <div className="mb-4">
          <Alert tone="warn">Sent back by QA: “{sample.reject_reason}”. Fix the boxes and submit again.</Alert>
        </div>
      )}
      {!editable && (
        <div className="mb-4">
          <Alert tone="info">This image is in the training pool. Only approvers can change it.</Alert>
        </div>
      )}
      {message && (
        <div className="mb-4" aria-live="polite">
          <Alert tone={message.tone}>{message.text}</Alert>
        </div>
      )}

      <section className="panel p-4">
        <Annotator
          imageUrl={`/api/samples/${sample.id}/image`}
          width={sample.width}
          height={sample.height}
          classes={classes}
          history={history}
          activeClassId={activeClass}
          onActiveClassChange={setActiveClass}
          suggestions={suggestions}
          onAcceptSuggestion={accept}
          readOnly={!editable}
        />
      </section>

      {editable && (
        <div className="sticky bottom-0 z-10 -mx-4 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          {canCreate && (
            <button type="button" className="btn" disabled={suggest.isPending} onClick={() => suggest.mutate()}>
              {suggest.isPending ? <Spinner /> : <Sparkles className="size-4" aria-hidden />} Suggest boxes
            </button>
          )}
          {(isOwner || canApprove) && (
            <button type="button" className="btn btn-quiet text-critical" onClick={() => setDeleting(true)}>
              <Trash2 className="size-4" aria-hidden /> Delete
            </button>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button type="button" className="btn" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Spinner /> : <Save className="size-4" aria-hidden />} Save
              <kbd className="ml-1 hidden rounded border border-line px-1 text-[10px] text-ink-3 sm:inline">Ctrl S</kbd>
            </button>
            {canApprove && sample.status !== "rejected" && (
              <button type="button" className="btn" onClick={() => setRejecting(true)}>
                Send back
              </button>
            )}
            {canCreate && (sample.status === "draft" || sample.status === "rejected") && (
              <button type="button" className="btn btn-ink" disabled={transition.isPending} onClick={() => transition.mutate("submit")}>
                {transition.isPending && transition.variables === "submit" && <Spinner />} Submit for QA
              </button>
            )}
            {canApprove && (
              <button type="button" className="btn btn-ink" disabled={transition.isPending} onClick={() => transition.mutate("approve")}>
                {transition.isPending && transition.variables === "approve" && <Spinner />}
                {sample.status === "approved" ? "Save to pool" : "Approve"}
              </button>
            )}
          </div>
        </div>
      )}

      <RejectDialog open={rejecting} sampleId={sample.id} onClose={() => setRejecting(false)} onDone={() => go(sample.next_id, "Sent back to the annotator.")} />
      <DeleteDialog open={deleting} sampleId={sample.id} onClose={() => setDeleting(false)} onDone={() => go(sample.next_id, "Deleted.")} />
    </>
  );
}

function iou(a: Box, b: Box) {
  const ix = Math.max(0, Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1));
  const iy = Math.max(0, Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1));
  const inter = ix * iy;
  const union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
  return union > 0 ? inter / union : 0;
}

function RejectDialog({ open, sampleId, onClose, onDone }: { open: boolean; sampleId: number; onClose: () => void; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const reject = useMutation({
    mutationFn: () => api(`/samples/${sampleId}/reject`, { method: "POST", json: { reason } }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["samples"] });
      onClose();
      onDone();
    },
  });
  return (
    <Dialog open={open} onClose={onClose} title="Send back to the annotator" description="Removed from the training pool until it is fixed and approved again.">
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          reject.mutate();
        }}
      >
        {reject.isError && <Alert tone="critical">{reject.error.message}</Alert>}
        <div>
          <label htmlFor="reject-reason" className="label">What needs fixing</label>
          <textarea id="reject-reason" rows={3} className="input h-auto py-2" required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. gloves on the left worker are not boxed" />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-ink" disabled={!reason.trim() || reject.isPending}>
            {reject.isPending && <Spinner />} Send back
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function DeleteDialog({ open, sampleId, onClose, onDone }: { open: boolean; sampleId: number; onClose: () => void; onDone: () => void }) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api(`/samples/${sampleId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["samples"] });
      onClose();
      onDone();
    },
  });
  return (
    <Dialog open={open} onClose={onClose} title="Delete this image?" description="Its boxes are removed and it leaves the training pool. Dataset versions already built keep their copy.">
      <div className="grid gap-4">
        {remove.isError && <Alert tone="critical">{remove.error.message}</Alert>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {remove.isPending && <Spinner />} Delete image
          </button>
        </div>
      </div>
    </Dialog>
  );
}
