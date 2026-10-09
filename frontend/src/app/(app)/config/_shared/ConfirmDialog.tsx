"use client";

import { useMutation } from "@tanstack/react-query";

import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";

/** Confirmation for destructive actions; shows the API's refusal message inline. */
export function ConfirmDialog({
  open,
  title,
  description,
  body,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  body: React.ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<unknown>;
  onClose: () => void;
}) {
  const action = useMutation({ mutationFn: onConfirm, onSuccess: onClose });
  const close = () => {
    action.reset();
    onClose();
  };
  return (
    <Dialog open={open} onClose={close} title={title} description={description}>
      <div className="grid gap-4">
        <div className="text-sm text-ink-2">{body}</div>
        {action.isError && <Alert tone="critical">{action.error.message}</Alert>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={close}>
            Cancel
          </button>
          <button type="button" className="btn btn-danger" disabled={action.isPending} onClick={() => action.mutate()}>
            {action.isPending && <Spinner />} {confirmLabel}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
