import type { Metadata } from "next";
import { Suspense } from "react";

import { PageLoading } from "@/components/ui/Spinner";

import { ReviewPage } from "./ReviewWorkspace";

export const metadata: Metadata = { title: "Review detection" };

export default function ReviewEventPage({ params }: PageProps<"/review/[id]">) {
  return (
    <Suspense fallback={<PageLoading label="Loading detection" />}>
      <ReviewPage idPromise={params.then((p) => p.id)} />
    </Suspense>
  );
}
