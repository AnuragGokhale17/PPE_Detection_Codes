"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface WorkerStatus {
  last_seen: string | null;
  online: boolean;
  info: Record<string, unknown>;
}

export interface SystemStatus {
  config_version: number;
  inference_paused: boolean;
  pause_reason: string | null;
  paused_by: string | null;
  active_model: { id: number; name: string } | null;
  workers: Partial<Record<"inference" | "trainer", WorkerStatus>>;
  training: { running_run_id: number | null; queued: number };
}

export const systemStatusKey = ["system", "status"] as const;

export function useSystemStatus(refetchMs = 30_000) {
  return useQuery({
    queryKey: systemStatusKey,
    queryFn: () => api<SystemStatus>("/system/status"),
    refetchInterval: refetchMs,
    staleTime: 10_000,
  });
}
