"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { SystemBanner } from "@/components/shell/SystemBanner";
import { PageLoading } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { canAny, useMe } from "@/lib/auth";
import { NAV } from "@/lib/nav";

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const me = useMe();
  const [menuOpen, setMenuOpen] = useState(false);

  const toLogin = useCallback(
    (reason?: string) => {
      queryClient.clear();
      const params = new URLSearchParams();
      if (reason) params.set("reason", reason);
      if (pathname && pathname !== "/") params.set("next", pathname);
      router.replace(`/login${params.size ? `?${params}` : ""}`);
    },
    [pathname, queryClient, router],
  );

  // Any API call that comes back 401 means the session lapsed
  useEffect(() => {
    const onUnauthorized = () => toLogin("expired");
    window.addEventListener("ppe:unauthorized", onUnauthorized);
    return () => window.removeEventListener("ppe:unauthorized", onUnauthorized);
  }, [toLogin]);

  useEffect(() => {
    if (me.isError) toLogin("expired");
  }, [me.isError, toLogin]);

  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      toLogin();
    }
  }

  if (!me.data) return <PageLoading label="Signing you in" />;
  const user = me.data;

  const groups = NAV.map((g) => ({ ...g, items: g.items.filter((i) => canAny(user, i.anyOf)) })).filter((g) => g.items.length);

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="px-5 pt-6 pb-5">
        <Logo width={120} />
        <p className="mt-3 text-[13px] font-bold text-ink">PPE safety</p>
        <p className="eyebrow">Smart Factory · Smart Safety</p>
      </div>
      <div className="flex-1 overflow-y-auto px-3">
        {groups.map((group) => (
          <div key={group.label} className="mb-5">
            <p className="eyebrow px-3 pb-1.5">{group.label}</p>
            <ul className="grid gap-0.5">
              {group.items.map((item) => {
                const active = pathname === item.href || pathname.startsWith(item.href + "/");
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setMenuOpen(false)}
                      className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition ${
                        active ? "bg-accent-50 text-accent-700" : "text-ink-2 hover:bg-surface-3 hover:text-ink"
                      }`}
                    >
                      <Icon className="size-4" aria-hidden />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-line p-4">
        <p className="truncate text-[13px] font-bold">{user.name}</p>
        <p className="truncate text-xs text-ink-3">{user.email}</p>
        <div className="mt-3 flex items-center justify-between">
          <span className={`pill ${user.role === "admin" ? "pill-info" : "pill-quiet"}`}>{user.role === "admin" ? "Administrator" : "User"}</span>
          <button type="button" className="btn btn-quiet btn-sm" onClick={signOut}>
            <LogOut className="size-3.5" aria-hidden /> Sign out
          </button>
        </div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:pl-64">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-line bg-surface lg:block">{sidebar}</aside>

      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-surface px-4 lg:hidden">
        <Logo width={96} />
        <button type="button" className="btn btn-quiet btn-sm" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
          <Menu className="size-5" aria-hidden />
        </button>
      </header>
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-ink/30" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-72 max-w-[85vw] bg-surface shadow-lg">
            <button type="button" className="btn btn-quiet btn-sm absolute top-4 right-3" aria-label="Close menu" onClick={() => setMenuOpen(false)}>
              <X className="size-4" aria-hidden />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <SystemBanner />
      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
    </div>
  );
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <p className="eyebrow-accent mb-1.5">{eyebrow}</p>}
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Forbidden() {
  return (
    <div className="panel mx-auto mt-10 max-w-md p-8 text-center">
      <h1 className="text-lg font-bold">You don&apos;t have access to this page</h1>
      <p className="mt-2 text-sm text-ink-2">Ask an administrator to grant you the permission if you need it.</p>
      <Link href="/dashboard" className="btn mt-5">Back to dashboard</Link>
    </div>
  );
}
