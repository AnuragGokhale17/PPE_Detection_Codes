import type { Metadata } from "next";

import { RecipientsConfig } from "./RecipientsConfig";

export const metadata: Metadata = { title: "Alert recipients" };

export default function RecipientsPage() {
  return <RecipientsConfig />;
}
