import type { Metadata } from "next";

import { PpeConfig } from "./PpeConfig";

export const metadata: Metadata = { title: "PPE & classes" };

export default function PpePage() {
  return <PpeConfig />;
}
