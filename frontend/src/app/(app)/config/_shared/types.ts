// Shapes returned by backend/app/routers/config.py

export interface CameraHealthInfo {
  online: boolean | null;
  last_checked: string | null;
}

export interface CameraRow {
  id: number;
  production_house_id: number;
  area: string;
  /** Password masked as •••• by the API */
  stream_url: string;
  enabled: boolean;
  scale_up: boolean;
  notes: string | null;
  ppe: string[];
  health: CameraHealthInfo | null;
  updated_at: string;
}

export interface HouseNode {
  id: number;
  name: string;
  cameras: CameraRow[];
}

export interface PlantNode {
  id: number;
  name: string;
  production_houses: HouseNode[];
}

export interface PpeItemRef {
  id: number;
  key: string;
  display_name: string;
  enabled: boolean;
}

export interface ConfigOverview {
  config_version: number;
  updated_at: string;
  updated_by: string | null;
  ppe_items: PpeItemRef[];
  plants: PlantNode[];
}

export interface PpeItemRow extends PpeItemRef {
  sort_order: number;
  /** Enabled cameras that require it */
  cameras: number;
}

export interface ClassRow {
  class_id: number;
  name: string;
  ppe_item_id: number | null;
  is_violation: boolean;
  threshold: number;
  enabled: boolean;
  in_active_model: boolean;
}

export interface PpeConfig {
  ppe_items: PpeItemRow[];
  classes: ClassRow[];
  active_model: { id: number; name: string } | null;
}

export type RecipientKind = "to" | "cc" | "bcc";

export interface Recipient {
  id?: number;
  email: string;
  kind: RecipientKind;
  designation: string | null;
}

export interface HouseRecipients {
  id: number;
  name: string;
  plant: string;
  cameras: number;
  recipients: Recipient[];
}

export interface RecipientsData {
  production_houses: HouseRecipients[];
  camera_health: Recipient[];
}

export interface ImportResult {
  created: number;
  updated: number;
  unchanged: number;
  skipped: number;
  unknown_ppe: string[];
}

export const overviewKey = ["config", "overview"] as const;
export const ppeKey = ["config", "ppe"] as const;
export const recipientsKey = ["config", "recipients"] as const;

export type CameraStatus = "disabled" | "online" | "offline" | "unreported";

export function cameraStatus(c: CameraRow): CameraStatus {
  if (!c.enabled) return "disabled";
  if (!c.health || c.health.online == null) return "unreported";
  return c.health.online ? "online" : "offline";
}
