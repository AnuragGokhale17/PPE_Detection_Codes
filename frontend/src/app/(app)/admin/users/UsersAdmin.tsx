"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Search, ShieldCheck, Trash2, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";

import { Forbidden, PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { passwordMeetsPolicy, PasswordRules } from "@/components/ui/PasswordRules";
import { PageLoading, Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";
import type { PermissionInfo, UserRow } from "@/lib/users";

const usersKey = ["admin", "users"] as const;
type Role = UserRow["role"];

export function UsersAdmin() {
  const { data: me } = useMe();
  const allowed = can(me, PERMISSIONS.usersManage);
  const users = useQuery({ queryKey: usersKey, queryFn: () => api<UserRow[]>("/users"), enabled: allowed });
  const catalogue = useQuery({
    queryKey: ["admin", "permissions"],
    queryFn: () => api<PermissionInfo[]>("/permissions"),
    enabled: allowed,
    staleTime: Infinity,
  });

  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [deleting, setDeleting] = useState<UserRow | null>(null);
  const [adding, setAdding] = useState(false);

  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = users.data ?? [];
    return q ? list.filter((u) => u.email.toLowerCase().includes(q) || u.name.toLowerCase().includes(q)) : list;
  }, [users.data, filter]);

  if (!allowed) return <Forbidden />;
  if (users.isPending || catalogue.isPending) return <PageLoading />;
  if (users.isError) return <Alert tone="critical">{users.error.message}</Alert>;

  const labels = Object.fromEntries((catalogue.data ?? []).map((p) => [p.key, p.label]));
  const admins = users.data.filter((u) => u.role === "admin").length;

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Users & permissions"
        description="Grant people access to review detections, annotate images or change camera and PPE configuration. Administrators hold every permission."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            <UserPlus className="size-4" aria-hidden /> Add user
          </button>
        }
      />

      <div className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
          <p className="text-sm text-ink-2">
            <span className="tabular font-bold text-ink">{users.data.length}</span> users ·{" "}
            <span className="tabular">{admins}</span> administrator{admins === 1 ? "" : "s"}
          </p>
          <label className="relative w-full max-w-xs">
            <span className="sr-only">Filter users</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              className="input h-9 pl-9"
              placeholder="Filter by name or email"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </label>
        </div>

        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-line bg-surface-2 text-xs text-ink-3">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">User</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Access</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <UserTableRow
                  key={u.id}
                  user={u}
                  isSelf={u.id === me?.id}
                  labels={labels}
                  onEdit={() => setEditing(u)}
                  onDelete={() => setDeleting(u)}
                />
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-ink-3">
                    No users match “{filter}”.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!editing} onClose={() => setEditing(null)} title="Edit access" description={editing?.email} wide>
        {editing && (
          <EditAccessForm
            key={editing.id}
            user={editing}
            isSelf={editing.id === me?.id}
            catalogue={catalogue.data ?? []}
            onDone={() => setEditing(null)}
          />
        )}
      </Dialog>

      <Dialog
        open={adding}
        onClose={() => setAdding(false)}
        title="Add user"
        description="They sign in with this password plus an emailed code. Share the password with them securely."
        wide
      >
        {adding && <AddUserForm catalogue={catalogue.data ?? []} onDone={() => setAdding(false)} />}
      </Dialog>

      <Dialog open={!!deleting} onClose={() => setDeleting(null)} title="Delete user?" description={deleting?.email}>
        {deleting && <DeleteUserForm key={deleting.id} user={deleting} onDone={() => setDeleting(null)} />}
      </Dialog>
    </>
  );
}

function StatusPills({ user }: { user: UserRow }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {user.is_active ? <span className="pill pill-ok">Active</span> : <span className="pill pill-quiet">Inactive</span>}
      {user.locked && <span className="pill pill-critical">Locked</span>}
      {user.password_expired && <span className="pill pill-warn">Password expired</span>}
    </div>
  );
}

function UserTableRow({
  user,
  isSelf,
  labels,
  onEdit,
  onDelete,
}: {
  user: UserRow;
  isSelf: boolean;
  labels: Record<string, string>;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: usersKey });
  const toggle = useMutation({
    mutationFn: () => api<UserRow>(`/users/${user.id}`, { method: "PATCH", json: { is_active: !user.is_active } }),
    onSuccess: refresh,
  });
  const unlock = useMutation({
    mutationFn: () => api<UserRow>(`/users/${user.id}/unlock`, { method: "POST" }),
    onSuccess: refresh,
  });
  const error = toggle.error ?? unlock.error;

  return (
    <tr className="border-b border-line last:border-0 hover:bg-surface-2">
      <td className="px-4 py-3">
        <p className="font-medium text-ink">
          {user.name} {isSelf && <span className="text-xs font-normal text-ink-3">(you)</span>}
        </p>
        <p className="text-xs text-ink-3">{user.email}</p>
      </td>
      <td className="px-4 py-3">
        <StatusPills user={user} />
      </td>
      <td className="px-4 py-3">
        {user.role === "admin" ? (
          <span className="pill pill-info">
            <ShieldCheck className="size-3" aria-hidden /> Administrator · all permissions
          </span>
        ) : user.granted.length ? (
          <div className="flex flex-wrap gap-1.5">
            {user.granted.map((p) => (
              <span key={p} className="pill pill-quiet">
                {labels[p] ?? p}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-xs text-ink-3">View dashboard only</span>
        )}
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-1.5">
          {user.locked && (
            <button type="button" className="btn btn-sm" onClick={() => unlock.mutate()} disabled={unlock.isPending}>
              <Lock className="size-3.5" aria-hidden /> Unlock
            </button>
          )}
          <button type="button" className="btn btn-sm" onClick={onEdit}>
            Edit access
          </button>
          {!isSelf && (
            <>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
                {user.is_active ? "Deactivate" : "Activate"}
              </button>
              <button
                type="button"
                className="btn btn-quiet btn-sm text-critical"
                aria-label={`Delete ${user.email}`}
                onClick={onDelete}
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            </>
          )}
        </div>
        {error && <p className="mt-1 text-right text-xs text-critical">{error.message}</p>}
      </td>
    </tr>
  );
}

function PermissionPicker({
  catalogue,
  role,
  value,
  onChange,
}: {
  catalogue: PermissionInfo[];
  role: Role;
  value: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  if (role === "admin") {
    return (
      <Alert tone="info">Administrators hold every permission, including retraining models and managing users.</Alert>
    );
  }
  return (
    <fieldset className="grid gap-2 sm:grid-cols-2">
      <legend className="label">Permissions</legend>
      {catalogue.map((p) => {
        const locked = p.default || !p.grantable;
        const checked = p.default || value.has(p.key);
        return (
          <label
            key={p.key}
            className={`flex gap-3 rounded-md border px-3 py-2.5 ${
              checked && !locked ? "border-accent-200 bg-accent-50" : "border-line"
            } ${locked ? "opacity-70" : "cursor-pointer hover:border-line-strong"}`}
          >
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-[var(--accent-600)]"
              checked={checked}
              disabled={locked}
              onChange={(e) => {
                const next = new Set(value);
                if (e.target.checked) next.add(p.key);
                else next.delete(p.key);
                onChange(next);
              }}
            />
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-ink">
                {p.label}
                {p.default && <span className="ml-2 text-xs font-normal text-ink-3">Everyone</span>}
                {!p.grantable && <span className="ml-2 text-xs font-normal text-ink-3">Administrators only</span>}
              </span>
              <span className="block text-xs text-ink-3">{p.description}</span>
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

function RoleSelect({ value, onChange, disabled }: { value: Role; onChange: (r: Role) => void; disabled?: boolean }) {
  return (
    <div>
      <label htmlFor="role" className="label">Role</label>
      <select
        id="role"
        className="input"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as Role)}
      >
        <option value="user">User</option>
        <option value="admin">Administrator</option>
      </select>
      {disabled && <p className="mt-1.5 text-xs text-ink-3">You can&apos;t change your own role.</p>}
    </div>
  );
}

function EditAccessForm({
  user,
  isSelf,
  catalogue,
  onDone,
}: {
  user: UserRow;
  isSelf: boolean;
  catalogue: PermissionInfo[];
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<Role>(user.role);
  const [granted, setGranted] = useState(() => new Set(user.granted));
  const save = useMutation({
    mutationFn: async () => {
      if (role !== user.role) await api(`/users/${user.id}`, { method: "PATCH", json: { role } });
      if (role === "user") await api(`/users/${user.id}/permissions`, { method: "PUT", json: { permissions: [...granted] } });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: usersKey });
      onDone();
    },
  });

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {save.isError && <Alert tone="critical">{save.error.message}</Alert>}
      <RoleSelect value={role} onChange={setRole} disabled={isSelf} />
      <PermissionPicker catalogue={catalogue} role={role} value={granted} onChange={setGranted} />
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className="btn" onClick={onDone}>Cancel</button>
        <button type="submit" className="btn btn-ink" disabled={save.isPending}>
          {save.isPending && <Spinner />} Save access
        </button>
      </div>
    </form>
  );
}

function AddUserForm({ catalogue, onDone }: { catalogue: PermissionInfo[]; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [granted, setGranted] = useState(() => new Set<string>());
  const create = useMutation({
    mutationFn: () =>
      api<UserRow>("/users", {
        method: "POST",
        json: { email, password, role, permissions: role === "user" ? [...granted] : [] },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: usersKey });
      onDone();
    },
  });

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      {create.isError && <Alert tone="critical">{create.error.message}</Alert>}
      <div>
        <label htmlFor="new-email" className="label">Email</label>
        <input
          id="new-email"
          type="email"
          className="input"
          placeholder="first.last@solargroup.com"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div>
        <label htmlFor="new-password" className="label">Initial password</label>
        <input
          id="new-password"
          type="password"
          className="input"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="mt-2">
          <PasswordRules password={password} />
        </div>
      </div>
      <RoleSelect value={role} onChange={setRole} />
      <PermissionPicker catalogue={catalogue} role={role} value={granted} onChange={setGranted} />
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className="btn" onClick={onDone}>Cancel</button>
        <button type="submit" className="btn btn-ink" disabled={create.isPending || !passwordMeetsPolicy(password)}>
          {create.isPending && <Spinner />} Create user
        </button>
      </div>
    </form>
  );
}

function DeleteUserForm({ user, onDone }: { user: UserRow; onDone: () => void }) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api(`/users/${user.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: usersKey });
      onDone();
    },
  });
  return (
    <div className="grid gap-4">
      <p className="text-sm text-ink-2">
        This removes the account and its password history. Audit-log entries are kept. To block sign-in but keep the
        account, deactivate it instead.
      </p>
      {remove.isError && <Alert tone="critical">{remove.error.message}</Alert>}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onDone}>Cancel</button>
        <button type="button" className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
          {remove.isPending && <Spinner />} Delete user
        </button>
      </div>
    </div>
  );
}
