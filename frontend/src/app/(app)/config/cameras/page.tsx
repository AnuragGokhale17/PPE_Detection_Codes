import type { Metadata } from "next";

import { CamerasConfig } from "./CamerasConfig";

export const metadata: Metadata = { title: "Cameras & areas" };

export default function CamerasPage() {
  return <CamerasConfig />;
}
