"use client";

import { useQuery } from "@tanstack/react-query";

import type { ClassInfo } from "@/components/annotator/types";
import { api } from "@/lib/api";

export function useClasses() {
  return useQuery({ queryKey: ["classes"], queryFn: () => api<ClassInfo[]>("/classes"), staleTime: 5 * 60_000 });
}
