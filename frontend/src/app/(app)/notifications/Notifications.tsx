"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronRight, Mail } from "lucide-react";
import { useState } from "react";

import { BarList } from "@/components/charts/BarList";
import { StatTile } from "@/components/charts/StatTile";
import { PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { DateRangePicker, PRESETS, type DateRange } from "@/components/ui/DateRangePicker";
import { EmptyState } from "@/components/ui/EmptyState";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { PageLoading, Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { formatDate, formatNumber } from "@/lib/format";

interface Datum {
  name: string;
  value: number;
}

interface Top {
  name: string | null;
  count: number;
}

interface TreeNode {
  name: string;
  email: string | null;
  designation: string | null;
  count: number;
  production_houses: Array<{ name: string; count: number; areas: Datum[] }>;
}

interface NotificationSummary {
  metrics: { total: number; top_recipient: Top; top_class: Top; top_production_house: Top };
  charts: { by_recipient: Datum[]; by_production_house: Datum[]; by_class: Datum[] };
  tree: TreeNode[];
}

interface Options {
  production_houses: string[];
  classes: string[];
  recipients: string[];
}

export function Notifications() {
  const [preset, setPreset] = useState("7d");
  const [range, setRange] = useState<DateRange>(() => PRESETS.find((p) => p.id === "7d")!.range());
  const [houses, setHouses] = useState<string[]>([]);
  const [classes, setClasses] = useState<string[]>([]);
  const [recipients, setRecipients] = useState<string[]>([]);
  const body = { ...range, production_houses: houses, classes, recipients };

  const options = useQuery({
    queryKey: ["dashboard", "options", range],
    queryFn: () => api<Options>("/dashboard/options", { method: "POST", json: range }),
    placeholderData: keepPreviousData,
  });
  const summary = useQuery({
    queryKey: ["notifications", body],
    queryFn: () => api<NotificationSummary>("/notifications/summary", { method: "POST", json: body }),
    placeholderData: keepPreviousData,
  });

  if (summary.isPending) return <PageLoading label="Loading alert emails" />;
  if (summary.isError) return <Alert tone="critical">{summary.error.message}</Alert>;
  const s = summary.data;
  const sameDay = range.start_date === range.end_date;

  return (
    <>
      <PageHeader
        eyebrow="Monitoring"
        title="Alert emails"
        description="Violation emails sent to supervisors. Each production house and area gets at most one email every 6 hours."
      />

      <section aria-label="Filters" className="mb-6 flex flex-wrap items-end gap-3">
        <DateRangePicker
          preset={preset}
          range={range}
          onChange={(p, r) => {
            setPreset(p);
            setRange(r);
          }}
        />
        <MultiSelect label="Production house" options={options.data?.production_houses ?? []} value={houses} onChange={setHouses} />
        <MultiSelect label="Violation" options={options.data?.classes ?? []} value={classes} onChange={setClasses} />
        <MultiSelect label="Recipients" options={options.data?.recipients ?? []} value={recipients} onChange={setRecipients} />
        {summary.isFetching && <Spinner className="mb-2.5 size-4 text-ink-3" />}
      </section>

      <div className={`grid grid-cols-1 gap-4 ${summary.isPlaceholderData ? "opacity-60" : ""}`}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <section className="panel-raised panel-brand p-6 lg:col-span-1">
            <p className="eyebrow-accent">{sameDay ? formatDate(range.start_date) : `${formatDate(range.start_date)} – ${formatDate(range.end_date)}`}</p>
            <p className="mt-2 text-[56px] leading-none font-bold tracking-[-0.038em]">{formatNumber(s.metrics.total)}</p>
            <p className="mt-3 text-sm text-ink-2">alert emails sent</p>
          </section>
          <StatTile label="Most alerted supervisor" value={s.metrics.top_recipient.name ?? "—"} context={s.metrics.top_recipient.count ? `${formatNumber(s.metrics.top_recipient.count)} emails` : undefined} />
          <StatTile label="Most frequent violation" value={s.metrics.top_class.name ?? "—"} context={s.metrics.top_class.count ? `in ${formatNumber(s.metrics.top_class.count)} emails` : undefined} />
          <StatTile label="Production house with most alerts" value={s.metrics.top_production_house.name ?? "—"} context={s.metrics.top_production_house.count ? `${formatNumber(s.metrics.top_production_house.count)} emails` : undefined} />
        </div>

        {s.metrics.total === 0 ? (
          <div className="panel">
            <EmptyState icon={Mail} title="No alert emails in this period">
              Emails are sent by the alert mailer when a violation is recorded and the production house has recipients configured.
            </EmptyState>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <section className="panel p-5">
                <h2 className="rule-head mb-4">By supervisor</h2>
                <BarList ariaLabel="Alert emails by supervisor" data={s.charts.by_recipient} limit={10} />
              </section>
              <section className="panel p-5">
                <h2 className="rule-head mb-4">By production house</h2>
                <BarList ariaLabel="Alert emails by production house" data={s.charts.by_production_house} limit={10} selected={houses} onSelect={(n) => setHouses(houses.includes(n) ? houses.filter((h) => h !== n) : [...houses, n])} />
              </section>
              <section className="panel p-5">
                <h2 className="rule-head mb-4">By violation type</h2>
                <BarList ariaLabel="Alert emails by violation type" data={[...s.charts.by_class].sort((a, b) => b.value - a.value)} />
              </section>
            </div>

            <section className="panel">
              <div className="border-b border-line px-5 py-4">
                <h2 className="text-sm font-bold">Who was alerted, where</h2>
                <p className="text-xs text-ink-3">Supervisor titles come from the alert recipients configuration.</p>
              </div>
              <ul className="divide-y divide-line">
                {s.tree.map((node) => (
                  <RecipientNode key={`${node.email}-${node.name}`} node={node} />
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </>
  );
}

function RecipientNode({ node }: { node: TreeNode }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-surface-2"
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronRight className={`size-4 shrink-0 text-ink-3 transition ${open ? "rotate-90" : ""}`} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{node.name || node.email}</span>
          <span className="block truncate text-xs text-ink-3">{node.designation ?? "No title set"} · {node.email}</span>
        </span>
        <span className="tabular text-sm font-bold">{formatNumber(node.count)}</span>
      </button>
      {open && (
        <div className="grid gap-3 bg-surface-2 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3 sm:pl-12">
          {node.production_houses.map((ph) => (
            <div key={ph.name} className="rounded-md border border-line bg-surface p-3">
              <p className="flex justify-between text-[13px] font-bold">
                {ph.name} <span className="tabular">{formatNumber(ph.count)}</span>
              </p>
              <ul className="mt-2 grid gap-0.5 text-xs text-ink-2">
                {ph.areas.map((a) => (
                  <li key={a.name} className="flex justify-between gap-3">
                    <span className="truncate">{a.name}</span>
                    <span className="tabular">{a.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}
