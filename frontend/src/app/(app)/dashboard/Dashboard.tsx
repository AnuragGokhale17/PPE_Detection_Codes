"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download, Eye, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { BarList } from "@/components/charts/BarList";
import { LineChart } from "@/components/charts/LineChart";
import { StatTile } from "@/components/charts/StatTile";
import { EventDialog, ReviewPill, type EventRow } from "@/components/events/EventDialog";
import { PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { DateRangePicker, PRESETS, type DateRange } from "@/components/ui/DateRangePicker";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { Pagination } from "@/components/ui/Pagination";
import { PageLoading, Spinner } from "@/components/ui/Spinner";
import { api, ApiError } from "@/lib/api";
import { formatDate, formatDateTime, formatNumber, formatPercent } from "@/lib/format";

interface Datum {
  name: string;
  value: number;
}

interface Summary {
  metrics: {
    total_violations: number;
    people_flagged: number;
    confirmed: number;
    false_positives: number;
    cameras_online: number;
    cameras_offline: number;
  };
  charts: {
    trend_unit: "hour" | "day";
    trend: Array<{ t: string; value: number }>;
    by_production_house: Datum[];
    by_area: Datum[];
    by_class: Datum[];
    by_shift: Datum[];
  };
  camera_health: {
    online: number;
    offline: number;
    offline_by_production_house: Datum[];
    offline_cameras: Array<{ plant: string | null; production_house: string | null; area: string | null; last_checked: string | null }>;
  };
  system: { inference_paused: boolean; pause_reason: string | null; inference_online: boolean };
}

interface Options {
  areas: string[];
  production_houses: string[];
  classes: string[];
  shifts: string[];
}

interface Filters {
  shifts: string[];
  areas: string[];
  production_houses: string[];
  classes: string[];
}

const EMPTY: Filters = { shifts: [], areas: [], production_houses: [], classes: [] };
const PAGE_SIZE = 20;

const hourFmt = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
const dayFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

export function Dashboard() {
  const [preset, setPreset] = useState("today");
  const [range, setRange] = useState<DateRange>(() => PRESETS[0].range());
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<EventRow | null>(null);
  const body = { ...range, ...filters };

  const options = useQuery({
    queryKey: ["dashboard", "options", range],
    queryFn: () => api<Options>("/dashboard/options", { method: "POST", json: range }),
    placeholderData: keepPreviousData,
  });
  const summary = useQuery({
    queryKey: ["dashboard", "summary", body],
    queryFn: () => api<Summary>("/dashboard/summary", { method: "POST", json: body }),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
  const events = useQuery({
    queryKey: ["dashboard", "events", body, page],
    queryFn: () =>
      api<{ items: EventRow[]; total: number }>("/dashboard/events", {
        method: "POST",
        json: { ...body, page, page_size: PAGE_SIZE },
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });

  const update = (patch: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(0);
  };
  const toggleIn = (key: keyof Filters, name: string) =>
    update({ [key]: filters[key].includes(name) ? filters[key].filter((x) => x !== name) : [...filters[key], name] });
  const activeFilters = Object.values(filters).some((v) => v.length);

  if (summary.isPending) return <PageLoading label="Loading dashboard" />;
  if (summary.isError) return <Alert tone="critical">{summary.error.message}</Alert>;
  const s = summary.data;
  const stale = summary.isPlaceholderData || summary.isFetching;

  return (
    <>
      <PageHeader
        eyebrow="Monitoring"
        title="PPE violations"
        description="Violations detected by the camera network. Events marked as false positives are excluded."
        actions={<ExportButton body={body} disabled={s.metrics.total_violations === 0} />}
      />

      <section aria-label="Filters" className="mb-6 flex flex-wrap items-end gap-3">
        <DateRangePicker
          preset={preset}
          range={range}
          onChange={(p, r) => {
            setPreset(p);
            setRange(r);
            setPage(0);
          }}
        />
        <MultiSelect label="Production house" options={options.data?.production_houses ?? []} value={filters.production_houses} onChange={(v) => update({ production_houses: v })} />
        <MultiSelect label="Area" options={options.data?.areas ?? []} value={filters.areas} onChange={(v) => update({ areas: v })} />
        <MultiSelect label="Violation" options={options.data?.classes ?? []} value={filters.classes} onChange={(v) => update({ classes: v })} />
        <MultiSelect label="Shift" options={options.data?.shifts ?? []} value={filters.shifts} onChange={(v) => update({ shifts: v })} />
        {activeFilters && (
          <button type="button" className="btn btn-quiet btn-sm mb-0.5" onClick={() => update(EMPTY)}>
            Clear filters
          </button>
        )}
        {stale && <Spinner className="mb-2.5 size-4 text-ink-3" />}
      </section>

      <div className={`grid grid-cols-1 gap-4 transition-opacity ${summary.isPlaceholderData ? "opacity-60" : ""}`}>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Hero summary={s} range={range} />
          <CameraHealth summary={s} />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatTile label="People flagged" value={s.metrics.people_flagged} context="Workers missing at least one required PPE item" />
          <StatTile label="Confirmed by reviewers" value={s.metrics.confirmed} context={`of ${formatNumber(s.metrics.total_violations)} events in this period`} />
          <StatTile label="Marked false positive" value={s.metrics.false_positives} context="Excluded from these numbers; used to retrain the model" />
        </div>

        <section className="panel p-5">
          <h2 className="rule-head mb-3">Violations per {s.charts.trend_unit}</h2>
          <LineChart
            points={s.charts.trend.map((p) => ({ key: p.t, y: p.value }))}
            formatKey={(k) => (s.charts.trend_unit === "hour" ? `${dayFmt.format(new Date(k))}, ${hourFmt.format(new Date(k))}` : formatDate(k.slice(0, 10)))}
            formatTick={(k) => (s.charts.trend_unit === "hour" ? hourFmt.format(new Date(k)) : dayFmt.format(new Date(k)))}
            ariaLabel={`Violations per ${s.charts.trend_unit}, ${range.start_date} to ${range.end_date}`}
            valueLabel="Violations"
          />
        </section>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ChartPanel title="By production house" hint="Select a house to filter">
            <BarList
              ariaLabel="Violations by production house"
              data={s.charts.by_production_house}
              limit={12}
              selected={filters.production_houses}
              onSelect={(n) => toggleIn("production_houses", n)}
            />
          </ChartPanel>
          <ChartPanel title="By violation type" hint="An event can include several types">
            <BarList
              ariaLabel="Violations by type"
              data={[...s.charts.by_class].sort((a, b) => b.value - a.value)}
              selected={filters.classes}
              onSelect={(n) => toggleIn("classes", n)}
            />
          </ChartPanel>
          <ChartPanel title="Areas with the most violations">
            <BarList ariaLabel="Top areas" data={s.charts.by_area} limit={10} selected={filters.areas} onSelect={(n) => toggleIn("areas", n)} />
          </ChartPanel>
          <ChartPanel title="By shift" hint="A 06:00–14:30 · B 14:30–23:00 · C 23:00–06:00">
            <BarList ariaLabel="Violations by shift" data={s.charts.by_shift} selected={filters.shifts} onSelect={(n) => toggleIn("shifts", n)} />
          </ChartPanel>
        </div>

        <EventsTable
          data={events.data}
          loading={events.isPending}
          dim={events.isPlaceholderData}
          page={page}
          onPage={setPage}
          onOpen={setSelected}
        />

        <OfflineCameras cameras={s.camera_health.offline_cameras} />
      </div>

      <EventDialog event={selected} onClose={() => setSelected(null)} />
    </>
  );
}

function ChartPanel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="panel p-5">
      <h2 className="rule-head">{title}</h2>
      {hint && <p className="mt-1 text-xs text-ink-3">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Hero({ summary, range }: { summary: Summary; range: DateRange }) {
  const m = summary.metrics;
  const topClass = [...summary.charts.by_class].sort((a, b) => b.value - a.value)[0];
  const topHouse = summary.charts.by_production_house[0];
  const topArea = summary.charts.by_area[0];
  const sameDay = range.start_date === range.end_date;

  let recommendation = "No violations recorded for this selection.";
  if (m.total_violations > 0 && topClass && topHouse) {
    const share = topClass.value / Math.max(1, m.total_violations);
    recommendation = `${topClass.name} is the most common issue (${formatPercent(share, 0)} of events). ${topHouse.name} has the most violations${
      topArea ? `, led by ${topArea.name}` : ""
    }. Brief the shift in charge there first.`;
  }

  return (
    <section className="panel-raised panel-brand p-6 lg:col-span-2">
      <p className="eyebrow-accent">Violations {sameDay ? `on ${formatDate(range.start_date)}` : `${formatDate(range.start_date)} – ${formatDate(range.end_date)}`}</p>
      <p className="mt-2 text-[56px] leading-none font-bold tracking-[-0.038em] text-ink">{formatNumber(m.total_violations)}</p>
      <p className="mt-4 max-w-2xl text-sm text-ink-2">{recommendation}</p>
    </section>
  );
}

function CameraHealth({ summary }: { summary: Summary }) {
  const h = summary.camera_health;
  const total = h.online + h.offline;
  const sys = summary.system;
  return (
    <section className="panel p-5">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-bold">Camera network</h2>
        {sys.inference_paused ? (
          <span className="pill pill-warn">Detection paused</span>
        ) : sys.inference_online ? (
          <span className="pill pill-ok">
            <span className="live-dot" aria-hidden /> Live
          </span>
        ) : (
          <span className="pill pill-critical">Detection offline</span>
        )}
      </div>
      <p className="mt-3 text-[28px] leading-tight font-bold">
        {formatNumber(h.online)}
        <span className="text-base font-medium text-ink-3"> / {formatNumber(total)} online</span>
      </p>
      <div className="mt-2 h-1.5 rounded-full bg-critical-surface" aria-hidden>
        <div className="h-full rounded-full bg-data" style={{ width: `${total ? (h.online / total) * 100 : 0}%` }} />
      </div>
      {h.offline > 0 ? (
        <>
          <p className="mt-3 text-xs text-critical">{formatNumber(h.offline)} offline. Most affected houses:</p>
          <ul className="mt-2 grid gap-1 text-[13px]">
            {h.offline_by_production_house.slice(0, 4).map((d) => (
              <li key={d.name} className="flex justify-between">
                <span className="text-ink-2">{d.name}</span>
                <span className="tabular font-medium">{d.value}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-3 text-xs text-ink-3">{total ? "Every camera reported in at its last check." : "No camera status reported yet."}</p>
      )}
    </section>
  );
}

function EventsTable({
  data,
  loading,
  dim,
  page,
  onPage,
  onOpen,
}: {
  data?: { items: EventRow[]; total: number };
  loading: boolean;
  dim: boolean;
  page: number;
  onPage: (p: number) => void;
  onOpen: (e: EventRow) => void;
}) {
  return (
    <section className="panel">
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <h2 className="text-sm font-bold">Events</h2>
        {data && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={onPage} />}
      </div>
      {loading ? (
        <PageLoading />
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-line bg-surface-2 text-xs text-ink-3">
              <tr>
                <th scope="col" className="px-5 py-2.5 font-medium">When</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Production house</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Area</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Violations</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Review</th>
                <th scope="col" className="px-5 py-2.5 text-right font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className={dim ? "opacity-60" : ""}>
              {data?.items.map((e) => (
                <tr key={e.id} className="border-b border-line last:border-0 hover:bg-surface-2">
                  <td className="tabular px-5 py-2.5 whitespace-nowrap text-ink-2">
                    {formatDate(e.date)} <span className="text-ink">{e.time?.slice(0, 5)}</span>
                  </td>
                  <td className="px-3 py-2.5 font-medium">{e.production_house}</td>
                  <td className="px-3 py-2.5 text-ink-2">{e.area}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {e.classes.map((c) => (
                        <span key={c} className="pill pill-critical">{c}</span>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <ReviewPill status={e.review_status} />
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    <button type="button" className="btn btn-sm" onClick={() => onOpen(e)}>
                      <Eye className="size-3.5" aria-hidden /> View
                    </button>
                  </td>
                </tr>
              ))}
              {data?.items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-ink-3">No violations match these filters.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function OfflineCameras({ cameras }: { cameras: Summary["camera_health"]["offline_cameras"] }) {
  const [query, setQuery] = useState("");
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? cameras.filter((c) => `${c.production_house} ${c.area} ${c.plant}`.toLowerCase().includes(q)) : cameras;
  }, [cameras, query]);
  if (!cameras.length) return null;
  return (
    <section className="panel">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-sm font-bold">Offline cameras</h2>
          <p className="text-xs text-ink-3">Unreachable at their last check. Share with the network team for a site visit.</p>
        </div>
        <label className="relative w-full max-w-xs">
          <span className="sr-only">Search offline cameras</span>
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <input className="input h-9 pl-9" placeholder="Search house or area" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
      </div>
      <div className="relative max-h-80 overflow-auto">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead className="sticky top-0 border-b border-line bg-surface-2 text-xs text-ink-3">
            <tr>
              <th scope="col" className="px-5 py-2 font-medium">Production house</th>
              <th scope="col" className="px-3 py-2 font-medium">Area</th>
              <th scope="col" className="px-3 py-2 font-medium">Last check</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c, i) => (
              <tr key={`${c.production_house}-${c.area}-${i}`} className="border-b border-line last:border-0">
                <td className="px-5 py-2 font-medium">{c.production_house}</td>
                <td className="px-3 py-2 text-ink-2">{c.area}</td>
                <td className="tabular px-3 py-2 text-ink-3">{formatDateTime(c.last_checked)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ExportButton({ body, disabled }: { body: object; disabled: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/dashboard/export", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail;
        throw new ApiError(res.status, typeof detail === "string" ? detail : "Export failed.");
      }
      const blob = await res.blob();
      const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "PPE_Report.xlsx";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="text-right">
      <button type="button" className="btn btn-ink" disabled={busy || disabled} onClick={download}>
        {busy ? <Spinner /> : <Download className="size-4" aria-hidden />} Export Excel
      </button>
      {error && <p className="mt-1 text-xs text-critical">{error}</p>}
    </div>
  );
}
