"use client";

import { useMutation } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";

import type { Recipient, RecipientKind } from "../_shared/types";

interface Row {
  rid: number;
  email: string;
  kind: RecipientKind;
  designation: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
let nextRid = 1;

function toRows(recipients: Recipient[]): Row[] {
  return recipients.map((r) => ({ rid: nextRid++, email: r.email, kind: r.kind, designation: r.designation ?? "" }));
}

function normalise(rows: Array<{ email: string; kind: RecipientKind; designation: string | null }>) {
  return rows
    .filter((r) => r.email.trim())
    .map((r) => ({ email: r.email.trim().toLowerCase(), kind: r.kind, designation: (r.designation ?? "").trim() || null }));
}

/** Order-insensitive fingerprint: the server returns recipients sorted, the editor keeps typing order. */
function fingerprint(list: ReturnType<typeof normalise>) {
  return JSON.stringify([...list].sort((a, b) => a.email.localeCompare(b.email) || a.kind.localeCompare(b.kind)));
}

/**
 * Editable recipient list. `requireTo` mirrors the API rule for production houses:
 * at least one To recipient, or none at all.
 */
export function RecipientEditor({
  idPrefix,
  initial,
  withDesignation,
  requireTo,
  onSave,
  saveLabel,
  primary,
}: {
  idPrefix: string;
  initial: Recipient[];
  withDesignation: boolean;
  requireTo: boolean;
  onSave: (recipients: ReturnType<typeof normalise>) => Promise<unknown>;
  saveLabel: string;
  primary?: boolean;
}) {
  const [rows, setRows] = useState<Row[]>(() => toRows(initial));
  const [saved, setSaved] = useState(false);
  const save = useMutation({ mutationFn: () => onSave(normalise(rows)), onSuccess: () => setSaved(true) });

  const clean = normalise(rows);
  const invalid = clean.filter((r) => !EMAIL_RE.test(r.email)).map((r) => r.email);
  const missingTo = requireTo && clean.length > 0 && !clean.some((r) => r.kind === "to");
  const dirty = fingerprint(clean) !== fingerprint(normalise(initial));

  const update = (rid: number, patch: Partial<Row>) => {
    setSaved(false);
    setRows((rs) => rs.map((r) => (r.rid === rid ? { ...r, ...patch } : r)));
  };

  return (
    <form
      className="grid gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!invalid.length && !missingTo) save.mutate();
      }}
    >
      {rows.length === 0 && <p className="text-sm text-ink-3">No recipients. Nobody is emailed.</p>}
      {rows.map((row, i) => (
        <div
          key={row.rid}
          className={`grid gap-2 ${withDesignation ? "sm:grid-cols-[minmax(0,1.4fr)_6rem_minmax(0,1fr)_auto]" : "sm:grid-cols-[minmax(0,1fr)_6rem_auto]"} items-end`}
        >
          <div>
            <label htmlFor={`${idPrefix}-email-${row.rid}`} className={i === 0 ? "label" : "label sm:sr-only"}>
              Email
            </label>
            <input
              id={`${idPrefix}-email-${row.rid}`}
              type="email"
              className="input"
              placeholder="first.last@solargroup.com"
              aria-invalid={!!row.email.trim() && !EMAIL_RE.test(row.email.trim())}
              value={row.email}
              onChange={(e) => update(row.rid, { email: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor={`${idPrefix}-kind-${row.rid}`} className={i === 0 ? "label" : "label sm:sr-only"}>
              Field
            </label>
            <select
              id={`${idPrefix}-kind-${row.rid}`}
              className="input"
              value={row.kind}
              onChange={(e) => update(row.rid, { kind: e.target.value as RecipientKind })}
            >
              <option value="to">To</option>
              <option value="cc">Cc</option>
              <option value="bcc">Bcc</option>
            </select>
          </div>
          {withDesignation && (
            <div>
              <label htmlFor={`${idPrefix}-role-${row.rid}`} className={i === 0 ? "label" : "label sm:sr-only"}>
                Designation (optional)
              </label>
              <input
                id={`${idPrefix}-role-${row.rid}`}
                className="input"
                maxLength={150}
                placeholder="e.g. Bulk & Chemical"
                value={row.designation}
                onChange={(e) => update(row.rid, { designation: e.target.value })}
              />
            </div>
          )}
          <button
            type="button"
            className="btn btn-quiet h-10"
            aria-label={`Remove ${row.email || "recipient"}`}
            onClick={() => {
              setSaved(false);
              setRows((rs) => rs.filter((r) => r.rid !== row.rid));
            }}
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
      ))}

      <div>
        <button
          type="button"
          className="btn btn-quiet btn-sm"
          onClick={() => {
            setSaved(false);
            setRows((rs) => [...rs, { rid: nextRid++, email: "", kind: rs.some((r) => r.kind === "to") ? "cc" : "to", designation: "" }]);
          }}
        >
          <Plus className="size-3.5" aria-hidden /> Add recipient
        </button>
      </div>

      {invalid.length > 0 && <Alert tone="warn">Check these addresses: {invalid.join(", ")}</Alert>}
      {missingTo && <Alert tone="warn">Add at least one To recipient, or remove them all.</Alert>}
      {save.isError && <Alert tone="critical">{save.error.message}</Alert>}
      {saved && !dirty && !save.isError && <Alert tone="ok">Saved. The next alert email uses this list.</Alert>}

      <div className="flex justify-end gap-2">
        {dirty && (
          <button
            type="button"
            className="btn"
            onClick={() => {
              setRows(toRows(initial));
              save.reset();
            }}
          >
            Discard changes
          </button>
        )}
        <button
          type="submit"
          className={`btn ${primary ? "btn-primary" : "btn-ink"}`}
          disabled={!dirty || save.isPending || invalid.length > 0 || missingTo}
        >
          {save.isPending && <Spinner />} {saveLabel}
        </button>
      </div>
    </form>
  );
}
