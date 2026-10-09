"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { Forbidden, PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { PageLoading } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";

interface AuditEntry {
  id: number;
  timestamp: string;
  user_email: string | null;
  action: string;
  details: string | null;
  ip_address: string | null;
}

const PAGE_SIZE = 50;
const formatter = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "medium" });

function actionTone(action: string) {
  if (/fail|delete|deactivat/i.test(action)) return "pill-critical";
  if (/permission|role|update|toggle|unlock/i.test(action)) return "pill-warn";
  if (/success|add/i.test(action)) return "pill-ok";
  return "pill-quiet";
}

export function AuditLog() {
  const { data: me } = useMe();
  const allowed = can(me, PERMISSIONS.usersManage);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const q = useDeferredValue(query.trim());

  const logs = useQuery({
    queryKey: ["admin", "audit", q, page],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
      if (q) params.set("q", q);
      return api<{ items: AuditEntry[]; total: number }>(`/audit-logs?${params}`);
    },
    enabled: allowed,
    placeholderData: keepPreviousData,
  });

  if (!allowed) return <Forbidden />;

  const total = logs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Audit log"
        description="Sign-ins, account changes and permission grants. Configuration and review actions appear here too as they move to the new portal."
      />
      <div className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
          <label className="relative w-full max-w-sm">
            <span className="sr-only">Search the audit log</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              className="input h-9 pl-9"
              placeholder="Search user, action or details"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
              }}
            />
          </label>
          <p className="tabular text-sm text-ink-3">{total.toLocaleString("en-IN")} entries</p>
        </div>

        {logs.isPending ? (
          <PageLoading />
        ) : logs.isError ? (
          <div className="p-4">
            <Alert tone="critical">{logs.error.message}</Alert>
          </div>
        ) : (
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-line bg-surface-2 text-xs text-ink-3">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">When</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">User</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Action</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Details</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">IP</th>
                </tr>
              </thead>
              <tbody className={logs.isPlaceholderData ? "opacity-60" : ""}>
                {logs.data.items.map((e) => (
                  <tr key={e.id} className="border-b border-line last:border-0 align-top">
                    <td className="tabular px-4 py-2.5 whitespace-nowrap text-ink-2">{formatter.format(new Date(e.timestamp))}</td>
                    <td className="px-4 py-2.5">{e.user_email ?? "—"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`pill ${actionTone(e.action)}`}>{e.action}</span>
                    </td>
                    <td className="px-4 py-2.5 text-ink-2">{e.details ?? ""}</td>
                    <td className="tabular px-4 py-2.5 text-xs text-ink-3">{e.ip_address ?? ""}</td>
                  </tr>
                ))}
                {logs.data.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-ink-3">No entries found.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-line p-3">
          <span className="tabular mr-2 text-xs text-ink-3">
            Page {page + 1} of {pages}
          </span>
          <button type="button" className="btn btn-sm" aria-label="Previous page" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            <ChevronLeft className="size-4" aria-hidden />
          </button>
          <button type="button" className="btn btn-sm" aria-label="Next page" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
            <ChevronRight className="size-4" aria-hidden />
          </button>
        </div>
      </div>
    </>
  );
}
