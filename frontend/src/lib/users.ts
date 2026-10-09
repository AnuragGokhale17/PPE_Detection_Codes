export interface PermissionInfo {
  key: string;
  label: string;
  description: string;
  grantable: boolean;
  default: boolean;
}

export interface UserRow {
  id: number;
  email: string;
  name: string;
  role: "admin" | "user";
  is_active: boolean;
  locked: boolean;
  password_expired: boolean;
  granted: string[];
  effective: string[];
}
