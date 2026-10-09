"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ScanSearch } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ReviewPill, type EventRow } from "@/components/events/EventDialog";
import { Forbidden, PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/components/ui/Pagination";
import { PageLoading } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";

const TABS = [
  { id: "unreviewed", label: "Not reviewed" },
  { id: "confirmed", label: "Confirmed" },
  { id: "false_positive", label: "False positives" },
  { id: "all", label: "All" },
] as const;
const PAGE_SIZE = 24;

export function ReviewQueue() {
  const { data: me } = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const status = params.get("status") ?? "unreviewed";
  const page = Number(params.get("page") ?? 0);
  const cleanOnly = params.get("clean") === "1";

  const setParam = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v == null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`${pathname}?${next}`);
  };

  const allowed = can(me, PERMISSIONS.violationsReview);
  const queue = useQuery({
    queryKey: ["review", "queue", status, page, cleanOnly],
    queryFn: () =>
      api<{ total: number; items: EventRow[] }>(
        `/events?${new URLSearchParams({ status, page: String(page), page_size: String(PAGE_SIZE), clean_frame_only: String(cleanOnly) })}`,
      ),
    enabled: allowed,
    placeholderData: keepPreviousData,
  });

  if (!allowed) return <Forbidden />;

  return (
    <>
      <PageHeader
        eyebrow="Model quality"
        title="Review detections"
        description="Confirm real violations and mark false alarms. Correcting the boxes on a clean frame turns it into YOLO training data for the next model."
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Review status" className="flex flex-wrap rounded-md border border-line bg-surface p-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={status === t.id}
              onClick={() => setParam({ status: t.id, page: null })}
              className={`rounded-[5px] px-3 py-1.5 text-[13px] font-medium ${status === t.id ? "bg-accent-50 text-accent-700" : "text-ink-2 hover:bg-surface-3"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <Switch
          checked={cleanOnly}
          onChange={(v) => setParam({ clean: v ? "1" : null, page: null })}
          label="Only events usable for training"
          description="Recorded with a clean frame (v2 inference)"
        />
      </div>

      {queue.isPending ? (
        <PageLoading />
      ) : queue.isError ? (
        <Alert tone="critical">{queue.error.message}</Alert>
      ) : queue.data.items.length === 0 ? (
        <div className="panel">
          <EmptyState icon={ScanSearch} title={status === "unreviewed" ? "Nothing waiting for review" : "No events here yet"}>
            {status === "unreviewed" ? "New detections appear here as the cameras record them." : null}
          </EmptyState>
        </div>
      ) : (
        <>
          <p className="mb-3 text-sm text-ink-3">
            <span className="tabular font-bold text-ink">{formatNumber(queue.data.total)}</span> events
          </p>
          <ul className={`grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 ${queue.isPlaceholderData ? "opacity-60" : ""}`}>
            {queue.data.items.map((e) => (
              <li key={e.id}>
                <Link href={`/review/${e.id}`} className="panel block overflow-hidden transition hover:shadow-md focus-visible:ring-3 focus-visible:ring-accent-200 focus-visible:outline-none">
                  <div className="aspect-video bg-surface-sunken">
                    {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                    <img src={`/api/events/${e.id}/image`} alt="" loading="lazy" className="h-full w-full object-cover" />
                  </div>
                  <div className="grid gap-1.5 p-3">
                    <p className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-bold">{e.production_house}</span>
                      <span className="tabular shrink-0 text-xs text-ink-3">
                        {formatDate(e.date)} {e.time?.slice(0, 5)}
                      </span>
                    </p>
                    <p className="truncate text-xs text-ink-2">{e.area}</p>
                    <div className="flex flex-wrap gap-1">
                      {e.classes.map((c) => (
                        <span key={c} className="pill pill-critical">{c}</span>
                      ))}
                      <ReviewPill status={e.review_status} />
                      {!e.has_clean_frame && <span className="pill pill-quiet">Verdict only</span>}
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <div className="mt-4">
            <Pagination page={page} pageSize={PAGE_SIZE} total={queue.data.total} onPage={(p) => setParam({ page: String(p) })} />
          </div>
        </>
      )}
    </>
  );
}
