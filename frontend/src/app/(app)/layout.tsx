import { Suspense } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { PageLoading } from "@/components/ui/Spinner";

// The shell reads the pathname (runtime data on dynamic routes), so it streams in
// behind a boundary; it shows a loader until the session check returns anyway.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<PageLoading label="Loading" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
