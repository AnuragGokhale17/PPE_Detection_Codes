"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Forbidden, PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageLoading } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";

import { recipientsKey, type HouseRecipients, type RecipientsData } from "../_shared/types";
import { RecipientEditor } from "./RecipientEditor";

function houseFlags(h: HouseRecipients) {
  const hasTo = h.recipients.some((r) => r.kind === "to");
  return {
    alertsGoNowhere: h.cameras > 0 && !hasTo,
    noCameras: h.cameras === 0 && h.recipients.length > 0,
  };
}

export function RecipientsConfig() {
  const { data: me } = useMe();
  const allowed = can(me, PERMISSIONS.configRecipients);
  const queryClient = useQueryClient();
  const data = useQuery({ queryKey: recipientsKey, queryFn: () => api<RecipientsData>("/config/recipients"), enabled: allowed });
  const [query, setQuery] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const houses = useMemo(() => data.data?.production_houses ?? [], [data.data]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return houses.filter((h) => {
      if (missingOnly && !houseFlags(h).alertsGoNowhere) return false;
      return !q || h.name.toLowerCase().includes(q) || h.recipients.some((r) => r.email.includes(q));
    });
  }, [houses, query, missingOnly]);

  if (!allowed) return <Forbidden />;
  if (data.isPending) return <PageLoading />;
  if (data.isError) return <Alert tone="critical">{data.error.message}</Alert>;

  const current = visible.find((h) => h.id === selectedId) ?? visible[0] ?? null;
  const missingCount = houses.filter((h) => houseFlags(h).alertsGoNowhere).length;
  const refresh = () => queryClient.invalidateQueries({ queryKey: recipientsKey });

  return (
    <>
      <PageHeader
        eyebrow="Configuration"
        title="Alert recipients"
        description="Who is emailed when a violation is detected in each production house, and who receives the daily camera health digest. Changes apply to the next email sent."
      />

      {missingCount > 0 && (
        <div className="mb-5">
          <Alert tone="warn">
            {missingCount} production house{missingCount === 1 ? " has" : "s have"} cameras but no To recipient, so their
            violation alerts go nowhere.{" "}
            {!missingOnly && (
              <button type="button" className="font-bold underline" onClick={() => setMissingOnly(true)}>
                Show them
              </button>
            )}
          </Alert>
        </div>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="panel p-3 lg:sticky lg:top-6" aria-label="Production houses">
          <label className="relative block">
            <span className="sr-only">Search production houses or recipients</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              className="input h-9 pl-9"
              placeholder="Search houses or emails"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="mt-3 px-1">
            <Switch checked={missingOnly} onChange={setMissingOnly} label="Missing recipients only" />
          </div>
          <ul className="mt-3 grid max-h-72 gap-0.5 overflow-y-auto pr-1 lg:max-h-[calc(100vh-16rem)]">
            {visible.map((h) => {
              const flags = houseFlags(h);
              const active = h.id === current?.id;
              return (
                <li key={h.id}>
                  <button
                    type="button"
                    aria-current={active ? "true" : undefined}
                    onClick={() => setSelectedId(h.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-[13px] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-200 ${
                      active ? "bg-accent-50 text-accent-700" : "text-ink-2 hover:bg-surface-3 hover:text-ink"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{h.name}</span>
                      <span className="tabular block text-[11px] text-ink-3">
                        {h.plant} · {h.recipients.length} recipient{h.recipients.length === 1 ? "" : "s"}
                      </span>
                    </span>
                    {flags.alertsGoNowhere && <span className="pill pill-warn shrink-0">Alerts go nowhere</span>}
                    {flags.noCameras && <span className="pill pill-quiet shrink-0">No cameras</span>}
                  </button>
                </li>
              );
            })}
            {visible.length === 0 && <li className="px-3 py-6 text-center text-sm text-ink-3">No production houses match.</li>}
          </ul>
        </aside>

        <div className="grid min-w-0 gap-5">
          <section className="panel" aria-labelledby="house-recipients-head">
            {current ? (
              <div className="p-4 sm:p-5">
                <div className="mb-4">
                  <p className="eyebrow">{current.plant} · violation alerts</p>
                  <h2 id="house-recipients-head" className="text-lg font-bold break-words">
                    {current.name}
                  </h2>
                  <p className="tabular text-xs text-ink-3">
                    {current.cameras} enabled camera{current.cameras === 1 ? "" : "s"} · alerts at most once every 6 hours per area
                  </p>
                </div>
                {houseFlags(current).noCameras && (
                  <div className="mb-4">
                    <Alert tone="info">
                      This production house has recipients but no cameras. That is often a naming mismatch with the camera
                      configuration (for example DF-01 here and DF01 on the cameras). Alerts are matched by name, so these
                      people receive nothing until the names agree.
                    </Alert>
                  </div>
                )}
                <RecipientEditor
                  key={`house-${current.id}`}
                  idPrefix={`house-${current.id}`}
                  initial={current.recipients}
                  withDesignation
                  requireTo
                  primary
                  saveLabel="Save recipients"
                  onSave={async (recipients) => {
                    await api(`/config/recipients/production-houses/${current.id}`, { method: "PUT", json: { recipients } });
                    await refresh();
                  }}
                />
                <p className="mt-4 text-xs text-ink-3">
                  The designation of the first To recipient is shown on the alert emails page (for example &ldquo;Bulk &amp;
                  Chemical&rdquo;).
                </p>
              </div>
            ) : (
              <EmptyState icon={Mail} title="No production houses to show">
                Add production houses on the cameras page first.
              </EmptyState>
            )}
          </section>

          <section className="panel p-4 sm:p-5" aria-labelledby="health-recipients-head">
            <p className="eyebrow">Plant-wide · daily at 10:00</p>
            <h2 id="health-recipients-head" className="text-lg font-bold">
              Camera health digest
            </h2>
            <p className="mb-4 text-xs text-ink-3">
              The list of offline cameras, sent once a day to the network and maintenance team. It is only sent when there is
              at least one To recipient.
            </p>
            <RecipientEditor
              key="health"
              idPrefix="health"
              initial={data.data.camera_health}
              withDesignation={false}
              requireTo
              saveLabel="Save digest recipients"
              onSave={async (recipients) => {
                await api("/config/recipients/camera-health", {
                  method: "PUT",
                  json: { recipients: recipients.map(({ email, kind }) => ({ email, kind })) },
                });
                await refresh();
              }}
            />
          </section>
        </div>
      </div>
    </>
  );
}
