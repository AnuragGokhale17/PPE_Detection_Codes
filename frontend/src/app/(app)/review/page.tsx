import type { Metadata } from "next";
import { Suspense } from "react";

import { PageLoading } from "@/components/ui/Spinner";

import { ReviewQueue } from "./ReviewQueue";

export const metadata: Metadata = { title: "Review detections" };

export default function ReviewPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <ReviewQueue />
    </Suspense>
  );
}
