import type { Metadata } from "next";
import { Suspense } from "react";

import { PageLoading } from "@/components/ui/Spinner";

import { SampleEditorPage } from "./SampleEditor";

export const metadata: Metadata = { title: "Annotate image" };

export default function AnnotateSamplePage({ params }: PageProps<"/annotate/[id]">) {
  return (
    <Suspense fallback={<PageLoading label="Loading image" />}>
      <SampleEditorPage idPromise={params.then((p) => p.id)} />
    </Suspense>
  );
}
