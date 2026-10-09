import type { Metadata } from "next";
import { Suspense } from "react";

import { PageLoading } from "@/components/ui/Spinner";

import { ResetPasswordForm } from "./ResetPasswordForm";

export const metadata: Metadata = { title: "Choose a new password" };

export default function ResetPasswordPage({ params }: PageProps<"/reset-password/[token]">) {
  return (
    <Suspense fallback={<PageLoading label="Checking link" />}>
      <ResetPasswordForm tokenPromise={params.then((p) => p.token)} />
    </Suspense>
  );
}
