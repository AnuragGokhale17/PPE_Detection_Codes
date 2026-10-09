import type { Metadata } from "next";
import { Suspense } from "react";

import { PageLoading } from "@/components/ui/Spinner";

import { AnnotateHome } from "./AnnotateHome";

export const metadata: Metadata = { title: "Annotate" };

export default function AnnotatePage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <AnnotateHome />
    </Suspense>
  );
}
