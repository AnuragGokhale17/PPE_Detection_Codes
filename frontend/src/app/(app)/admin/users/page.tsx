import type { Metadata } from "next";

import { UsersAdmin } from "./UsersAdmin";

export const metadata: Metadata = { title: "Users & permissions" };

export default function UsersPage() {
  return <UsersAdmin />;
}
