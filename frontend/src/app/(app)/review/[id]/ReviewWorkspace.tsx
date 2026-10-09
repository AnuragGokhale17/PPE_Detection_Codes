"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ExternalLink, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useState } from "react";

import { Annotator } from "@/components/annotator/Annotator";
import { toBox, toLabel, type Box, type ClassInfo, type Label } from "@/components/annotator/types";
import { useBoxHistory } from "@/components/annotator/useBoxHistory";
import { ReviewPill } from "@/components/events/EventDialog";
import { Forbidden } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { PageLoading, Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";
import { useClasses } from "@/lib/classes";
import { formatDate, formatDateTime } from "@/lib/format";

interface EventDetail {
  id: number;
  date: string | null;
  time: string | null;
  production_house: string | null;
  area: string | null;
  classes: string[];
  compliance: string | null;
  required_ppes: string | null;
  people_count: number | null;
  violator_count: number | null;
  has_clean_frame: boolean;
  frame: { width: number; height: number };
  review: { status: string | null; by: string | null; at: string | null; notes: string | null };
  labels: Label[];
  suggestions: Label[];
  sample: { id: number; status: string } | null;
  next_unreviewed_id: number | null;
}

export function ReviewPage({ idPromise }: { idPromise: Promise<string> }) {
  const id = use(idPromise);
  const { data: me } = useMe();
  const allowed = can(me, PERMISSIONS.violationsReview);
  const event = useQuery({
    queryKey: ["review", "event", id],
    queryFn: () => api<EventDetail>(`/events/${id}`),
    enabled: allowed,
  });
  const classes = useClasses();

  if (!allowed) return <Forbidden />;
  if (event.isPending || classes.isPending) return <PageLoading label="Loading detection" />;
  if (event.isError) return <Alert tone="critical">{event.error.message}</Alert>;
  if (classes.isError) return <Alert tone="critical">{classes.error.message}</Alert>;
  return <Workspace key={event.data.id} event={event.data} classes={classes.data} canApprove={can(me, PERMISSIONS.annotationsApprove)} />;
}

function Workspace({ event, classes, canApprove }: { event: EventDetail; classes: ClassInfo[]; canApprove: boolean }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const history = useBoxHistory(event.labels.map(toBox));
  const [suggestions, setSuggestions] = useState<Box[]>(() => event.suggestions.map(toBox));
  const [activeClass, setActiveClass] = useState(() => event.labels[0]?.class_id ?? classes.find((c) => c.enabled)?.class_id ?? 0);
  const [notes, setNotes] = useState(event.review.notes ?? "");
  const [saveForTraining, setSaveForTraining] = useState(event.has_clean_frame);
  const [approveNow, setApproveNow] = useState(canApprove);

  const review = useMutation({
    mutationFn: (verdict: "confirmed" | "false_positive") =>
      api<{ sample: { id: number; status: string } | null }>(`/events/${event.id}/review`, {
        method: "POST",
        json: {
          verdict,
          notes: notes.trim() || null,
          labels: saveForTraining ? history.boxes.map(toLabel) : null,
          approve: saveForTraining && approveNow,
        },
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);
      router.push(event.next_unreviewed_id ? `/review/${event.next_unreviewed_id}` : "/review");
    },
  });

  const accept = (s: Box) => {
    setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    history.commit((prev) => [...prev, { ...s, origin: "human" }]);
  };

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/review" className="btn btn-quiet btn-sm -ml-3 mb-1">
            <ArrowLeft className="size-4" aria-hidden /> Review queue
          </Link>
          <h1 className="text-xl font-bold tracking-tight">
            {event.production_house} · {event.area}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-2">
            <span className="tabular">
              {formatDate(event.date)} at {event.time}
            </span>
            <span aria-hidden>·</span>
            <span>Event #{event.id}</span>
            {event.classes.map((c) => (
              <span key={c} className="pill pill-critical">{c}</span>
            ))}
            <ReviewPill status={event.review.status} />
          </p>
        </div>
        <a href={`/api/events/${event.id}/image`} target="_blank" rel="noreferrer" className="btn btn-sm">
          <ExternalLink className="size-3.5" aria-hidden /> Original alert image
        </a>
      </div>

      {event.review.status && (
        <div className="mb-4">
          <Alert tone="info">
            Reviewed as {event.review.status === "false_positive" ? "a false positive" : "a confirmed violation"} by {event.review.by ?? "someone"} on{" "}
            {formatDateTime(event.review.at)}. Saving again replaces that review.
          </Alert>
        </div>
      )}

      <div>
        <section className="panel p-4">
          {event.has_clean_frame ? (
            <Annotator
              imageUrl={`/api/events/${event.id}/image?variant=raw`}
              width={event.frame.width}
              height={event.frame.height}
              classes={classes}
              history={history}
              activeClassId={activeClass}
              onActiveClassChange={setActiveClass}
              suggestions={suggestions}
              onAcceptSuggestion={accept}
              readOnly={!saveForTraining}
            />
          ) : (
            <div>
              <Alert tone="warn">
                This event was recorded before the clean-frame upgrade, so only the annotated alert image exists. You can record a verdict, but it can&apos;t become training data.
              </Alert>
              {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
              <img src={`/api/events/${event.id}/image`} alt="Alert image" className="mt-3 w-full rounded-md border border-line" />
            </div>
          )}
        </section>

      </div>

      <section className="panel mt-4 grid grid-cols-1 gap-5 p-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="grid content-start gap-3">
          <h2 className="text-sm font-bold">How to review</h2>
          <p className="text-xs text-ink-2">
            Box every PPE item you can see, not just the one that triggered the alert. YOLO learns from the whole frame. If the model was wrong, fix the box&apos;s class (for example <em>No Helmet</em> → <em>Helmet</em>) or delete it.
          </p>
          <dl className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-ink-3">Required here</dt>
              <dd className="font-medium">{event.required_ppes || "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-3">People flagged</dt>
              <dd className="font-medium">
                {event.violator_count ?? "?"} of {event.people_count ?? "?"}
              </dd>
            </div>
          </dl>
        </div>
        <div className="grid content-start gap-4">
          {event.has_clean_frame && (
            <Switch
              checked={saveForTraining}
              onChange={setSaveForTraining}
              label="Save the corrected boxes as training data"
              description={event.sample ? `Updates sample #${event.sample.id} (${event.sample.status})` : "Creates a YOLO sample from this frame"}
            />
          )}
          {saveForTraining && canApprove && (
            <Switch
              checked={approveNow}
              onChange={setApproveNow}
              label="Approve into the training pool now"
              description="Otherwise it waits in the annotation QA queue"
            />
          )}
          <div>
            <label htmlFor="notes" className="label">Notes (optional)</label>
            <textarea id="notes" rows={2} className="input h-auto py-2" placeholder="e.g. reflection on the helmet confused the model" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>
      </section>

      {/* Always-visible verdict bar, so the canvas can use the full width */}
      <div className="sticky bottom-0 z-10 -mx-4 mt-4 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        {review.isError && (
          <div className="mb-2">
            <Alert tone="critical">{review.error.message}</Alert>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-auto text-xs text-ink-3">
            {event.next_unreviewed_id ? "Saving opens the next unreviewed detection." : "Saving returns to the queue."}
          </p>
          <button type="button" className="btn h-10" disabled={review.isPending} onClick={() => review.mutate("false_positive")}>
            {review.isPending && review.variables === "false_positive" ? <Spinner /> : <XCircle className="size-4" aria-hidden />}
            False positive
          </button>
          <button type="button" className="btn btn-ink h-10" disabled={review.isPending} onClick={() => review.mutate("confirmed")}>
            {review.isPending && review.variables === "confirmed" ? <Spinner /> : <CheckCircle2 className="size-4" aria-hidden />}
            Real violation
          </button>
        </div>
      </div>
    </>
  );
}
