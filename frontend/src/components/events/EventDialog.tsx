"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";
import { formatDate } from "@/lib/format";

export interface EventRow {
  id: number;
  date: string | null;
  time: string | null;
  production_house: string | null;
  area: string | null;
  classes: string[];
  review_status: string | null;
  has_clean_frame: boolean;
  people_count?: number | null;
  violator_count?: number | null;
}

export function ReviewPill({ status }: { status: string | null }) {
  if (status === "confirmed") return <span className="pill pill-ok">Confirmed</span>;
  if (status === "false_positive") return <span className="pill pill-quiet">False positive</span>;
  return <span className="pill pill-info">Not reviewed</span>;
}

export function EventDialog({ event, onClose }: { event: EventRow | null; onClose: () => void }) {
  return (
    <Dialog
      open={!!event}
      onClose={onClose}
      title={event ? `${event.production_house} · ${event.area}` : ""}
      description={event ? `${formatDate(event.date)} at ${event.time} · event #${event.id}` : undefined}
      wide
    >
      {event && <EventBody key={event.id} event={event} onDone={onClose} />}
    </Dialog>
  );
}

function EventBody({ event, onDone }: { event: EventRow; onDone: () => void }) {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const [variant, setVariant] = useState<"annotated" | "raw">("annotated");
  const [failed, setFailed] = useState(false);
  const canReview = can(me, PERMISSIONS.violationsReview);

  const review = useMutation({
    mutationFn: (verdict: "confirmed" | "false_positive") =>
      api(`/events/${event.id}/review`, { method: "POST", json: { verdict } }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      await queryClient.invalidateQueries({ queryKey: ["review"] });
      onDone();
    },
  });

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {event.classes.map((c) => (
          <span key={c} className="pill pill-critical">{c}</span>
        ))}
        <ReviewPill status={event.review_status} />
        {event.violator_count != null && (
          <span className="text-xs text-ink-3">
            {event.violator_count} of {event.people_count ?? "?"} people flagged
          </span>
        )}
      </div>

      {event.has_clean_frame && (
        <div role="group" aria-label="Image" className="flex w-fit rounded-md border border-line p-0.5">
          {(["annotated", "raw"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={variant === v}
              onClick={() => {
                setVariant(v);
                setFailed(false);
              }}
              className={`rounded-[5px] px-2.5 py-1 text-xs font-medium ${variant === v ? "bg-accent-50 text-accent-700" : "text-ink-2"}`}
            >
              {v === "annotated" ? "With detections" : "Clean frame"}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-hidden rounded-md border border-line bg-surface-sunken">
        {failed ? (
          <p className="p-10 text-center text-sm text-ink-3">The image couldn&apos;t be loaded from storage.</p>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element -- authenticated API image, not a static asset
          <img
            src={`/api/events/${event.id}/image?variant=${variant}`}
            alt={`Detection at ${event.production_house} ${event.area}`}
            className="block h-auto w-full"
            onError={() => setFailed(true)}
          />
        )}
      </div>

      {review.isError && <Alert tone="critical">{review.error.message}</Alert>}

      {canReview && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {event.has_clean_frame && (
            <Link href={`/review/${event.id}`} className="btn btn-outline mr-auto">
              <ExternalLink className="size-4" aria-hidden /> Correct boxes for training
            </Link>
          )}
          <button type="button" className="btn" disabled={review.isPending} onClick={() => review.mutate("false_positive")}>
            {review.isPending && review.variables === "false_positive" ? <Spinner /> : <XCircle className="size-4" aria-hidden />}
            False positive
          </button>
          <button type="button" className="btn btn-ink" disabled={review.isPending} onClick={() => review.mutate("confirmed")}>
            {review.isPending && review.variables === "confirmed" ? <Spinner /> : <CheckCircle2 className="size-4" aria-hidden />}
            Confirm violation
          </button>
        </div>
      )}
    </div>
  );
}
