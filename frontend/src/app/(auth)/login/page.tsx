import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginFlow } from "./LoginFlow";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <Suspense>
      <LoginFlow />
    </Suspense>
  );
}
