"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";

import { overviewKey, type ImportResult } from "../_shared/types";

export function ExportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [includeDisabled, setIncludeDisabled] = useState(true);
  return (
    <Dialog open={open} onClose={onClose} title="Export camera list" description="Same JSON format as the old camera_list files.">
      <div className="grid gap-4">
        <Alert tone="warn">
          The file contains every camera&apos;s full stream address, including passwords. Store and share it like a
          password.
        </Alert>
        <Switch checked={includeDisabled} onChange={setIncludeDisabled} label="Include disabled cameras" />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <a
            className="btn btn-ink"
            href={`/api/config/cameras/export?include_disabled=${includeDisabled}`}
            download
            onClick={() => setTimeout(onClose, 300)}
          >
            <Download className="size-4" aria-hidden /> Download JSON
          </a>
        </div>
      </div>
    </Dialog>
  );
}

export function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Import camera list"
      description="Merges a camera_list JSON file (plant → production house → area) into the configuration."
      wide
    >
      {open && <ImportForm onClose={onClose} />}
    </Dialog>
  );
}

function ImportForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [enableNew, setEnableNew] = useState(true);
  const [updateExisting, setUpdateExisting] = useState(true);
  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file as File);
      form.append("enable_new", String(enableNew));
      form.append("update_existing", String(updateExisting));
      return api<ImportResult>("/config/cameras/import", { method: "POST", body: form });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: overviewKey }),
  });

  if (upload.isSuccess) {
    const r = upload.data;
    return (
      <div className="grid gap-4">
        <Alert tone="ok">Import finished. Live detection picks the changes up within about 30 seconds.</Alert>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            [
              ["Created", r.created],
              ["Updated", r.updated],
              ["Unchanged", r.unchanged],
              ["Skipped", r.skipped],
            ] as const
          ).map(([label, n]) => (
            <div key={label} className="rounded-md border border-line px-3 py-2">
              <dt className="eyebrow">{label}</dt>
              <dd className="text-xl font-bold">{formatNumber(n)}</dd>
            </div>
          ))}
        </dl>
        {r.unknown_ppe.length > 0 && (
          <Alert tone="warn">
            Ignored PPE names that don&apos;t match any configured PPE: {r.unknown_ppe.join(", ")}. Add them on the PPE
            page and import again, or set them per camera.
          </Alert>
        )}
        <div className="flex justify-end">
          <button type="button" className="btn btn-ink" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (file) upload.mutate();
      }}
    >
      {upload.isError && <Alert tone="critical">{upload.error.message}</Alert>}
      <div>
        <label htmlFor="import-file" className="label">Camera list file</label>
        <input
          id="import-file"
          type="file"
          accept="application/json,.json"
          required
          className="block w-full text-sm text-ink-2 file:mr-3 file:h-9 file:cursor-pointer file:rounded-md file:border file:border-line file:bg-surface file:px-4 file:text-[13px] file:font-bold file:text-ink hover:file:bg-surface-2"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </div>
      <Switch checked={enableNew} onChange={setEnableNew} label="Create new cameras enabled" description="Off: new cameras are added but not monitored until you enable them." />
      <Switch
        checked={updateExisting}
        onChange={setUpdateExisting}
        label="Update cameras that already exist"
        description="Overwrites their stream address and required PPE with the file's values."
      />
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn btn-ink" disabled={!file || upload.isPending}>
          {upload.isPending && <Spinner />} Import
        </button>
      </div>
    </form>
  );
}
