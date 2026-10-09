"use client";

import { PauseCircle } from "lucide-react";
import Link from "next/link";

import { can, PERMISSIONS, useMe } from "@/lib/auth";
import { useSystemStatus } from "@/lib/system";

/** Shown on every page while live detection is paused (retraining or a manual pause). */
export function SystemBanner() {
  const { data } = useSystemStatus();
  const { data: me } = useMe();
  if (!data?.inference_paused) return null;
  const training = data.training.running_run_id != null;
  return (
    <div role="status" className="border-b border-warn-line bg-warn-surface px-4 py-2 text-[13px] text-warn sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-3 gap-y-1">
        <PauseCircle className="size-4 shrink-0" aria-hidden />
        <span className="font-bold">Live PPE detection is paused.</span>
        <span>
          {training
            ? `The GPU is retraining the model (run #${data.training.running_run_id}). No new violations are recorded until it finishes.`
            : (data.pause_reason ?? "No new violations are recorded until it is resumed.")}
        </span>
        {can(me, PERMISSIONS.trainingManage) && (
          <Link href="/training" className="font-bold underline">
            Manage
          </Link>
        )}
      </div>
    </div>
  );
}
