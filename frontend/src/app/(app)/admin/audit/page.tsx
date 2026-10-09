import type { Metadata } from "next";

import { AuditLog } from "./AuditLog";

export const metadata: Metadata = { title: "Audit log" };

export default function AuditPage() {
  return <AuditLog />;
}
