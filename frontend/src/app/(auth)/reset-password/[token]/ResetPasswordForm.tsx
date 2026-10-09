"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { passwordMeetsPolicy, PasswordRules } from "@/components/ui/PasswordRules";
import { PageLoading, Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";

export function ResetPasswordForm({ tokenPromise }: { tokenPromise: Promise<string> }) {
  const token = use(tokenPromise);
  const info = useQuery({
    queryKey: ["reset-token", token],
    queryFn: () => api<{ valid: boolean; email_hint: string | null }>(`/auth/reset-password/${encodeURIComponent(token)}`),
    retry: false,
  });
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (info.isPending) return <PageLoading label="Checking link" />;

  if (done) {
    return (
      <div className="grid gap-5">
        <h1 className="text-xl font-bold">Password updated</h1>
        <Alert tone="ok">{done}</Alert>
        <Link href="/login" className="btn btn-primary h-10 w-full">Go to sign in</Link>
      </div>
    );
  }

  if (info.isError || !info.data?.valid) {
    return (
      <div className="grid gap-5">
        <h1 className="text-xl font-bold">This link no longer works</h1>
        <p className="text-sm text-ink-2">Reset links expire after 30 minutes and can only be used once.</p>
        <Link href="/forgot-password" className="btn btn-ink h-10 w-full">Request a new link</Link>
      </div>
    );
  }

  const mismatch = confirm.length > 0 && confirm !== password;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api<{ message: string }>("/auth/reset-password", {
        method: "POST",
        json: { token, password, confirm_password: confirm },
      });
      setDone(res.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-xl font-bold">Choose a new password</h1>
      <p className="mt-1.5 text-sm text-ink-2">For {info.data.email_hint}. You can&apos;t reuse any of your last 5 passwords.</p>
      <form className="mt-6 grid gap-4" onSubmit={submit}>
        {error && <Alert tone="critical">{error}</Alert>}
        <div>
          <label htmlFor="password" className="label">New password</label>
          <input id="password" type="password" className="input" autoComplete="new-password" required autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <PasswordRules password={password} />
        <div>
          <label htmlFor="confirm" className="label">Confirm new password</label>
          <input
            id="confirm"
            type="password"
            className="input"
            autoComplete="new-password"
            required
            aria-invalid={mismatch}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {mismatch && <p className="mt-1.5 text-xs text-critical">Passwords do not match.</p>}
        </div>
        <button type="submit" className="btn btn-primary h-10 w-full" disabled={busy || !passwordMeetsPolicy(password) || confirm !== password}>
          {busy && <Spinner />} Update password
        </button>
      </form>
    </div>
  );
}
