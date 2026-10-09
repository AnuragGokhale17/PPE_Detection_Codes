"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export const PERMISSIONS = {
  dashboardView: "dashboard.view",
  violationsReview: "violations.review",
  annotationsCreate: "annotations.create",
  annotationsApprove: "annotations.approve",
  configCameras: "config.cameras",
  configPpe: "config.ppe",
  configRecipients: "config.recipients",
  trainingManage: "training.manage",
  usersManage: "users.manage",
} as const;

export type PermissionKey = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

export interface Me {
  id: number;
  email: string;
  name: string;
  role: "admin" | "user";
  permissions: string[];
}

export const meQueryKey = ["auth", "me"] as const;

export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: () => api<Me>("/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
}

export function can(me: Me | undefined, permission: PermissionKey): boolean {
  return !!me?.permissions.includes(permission);
}

export function canAny(me: Me | undefined, permissions: PermissionKey[]): boolean {
  return permissions.some((p) => can(me, p));
}

export function safeNext(next: string | null): string {
  // Only allow same-site relative paths after sign-in
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}
