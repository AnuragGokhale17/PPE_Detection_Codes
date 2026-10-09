import {
  BellRing,
  BrainCircuit,
  Camera,
  HardHat,
  LayoutDashboard,
  Mail,
  PenTool,
  ScanSearch,
  ScrollText,
  Users,
  type LucideIcon,
} from "lucide-react";

import { PERMISSIONS, type PermissionKey } from "@/lib/auth";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown when the user holds any of these */
  anyOf: PermissionKey[];
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "Monitoring",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, anyOf: [PERMISSIONS.dashboardView] },
      { href: "/notifications", label: "Alert emails", icon: BellRing, anyOf: [PERMISSIONS.dashboardView] },
    ],
  },
  {
    label: "Model quality",
    items: [
      { href: "/review", label: "Review detections", icon: ScanSearch, anyOf: [PERMISSIONS.violationsReview] },
      {
        href: "/annotate",
        label: "Annotate",
        icon: PenTool,
        anyOf: [PERMISSIONS.annotationsCreate, PERMISSIONS.annotationsApprove],
      },
      { href: "/training", label: "Training & models", icon: BrainCircuit, anyOf: [PERMISSIONS.trainingManage] },
    ],
  },
  {
    label: "Configuration",
    items: [
      { href: "/config/cameras", label: "Cameras & areas", icon: Camera, anyOf: [PERMISSIONS.configCameras, PERMISSIONS.configPpe] },
      { href: "/config/ppe", label: "PPE & classes", icon: HardHat, anyOf: [PERMISSIONS.configPpe] },
      { href: "/config/recipients", label: "Alert recipients", icon: Mail, anyOf: [PERMISSIONS.configRecipients] },
    ],
  },
  {
    label: "Administration",
    items: [
      { href: "/admin/users", label: "Users & permissions", icon: Users, anyOf: [PERMISSIONS.usersManage] },
      { href: "/admin/audit", label: "Audit log", icon: ScrollText, anyOf: [PERMISSIONS.usersManage] },
    ],
  },
];
