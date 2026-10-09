"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";

export function ForgotPasswordForm() {
  const params = useSearchParams();
  const expired = params.get("reason") === "expired";
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api<{ message: string }>("/auth/forgot-password", { method: "POST", json: { email } });
      setSent(res.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <Link href="/login" className="btn btn-quiet btn-sm -ml-3 mb-4">
        <ArrowLeft className="size-4" aria-hidden /> Back to sign in
      </Link>
      <h1 className="text-xl font-bold">{expired ? "Your password has expired" : "Reset your password"}</h1>
      <p className="mt-1.5 text-sm text-ink-2">
        {expired
          ? "Passwords expire every 30 days. We'll email you a link to choose a new one."
          : "Enter your email and we'll send you a link to choose a new password."}
      </p>
      {sent ? (
        <div className="mt-6">
          <Alert tone="ok">{sent} The link expires in 30 minutes.</Alert>
        </div>
      ) : (
        <form className="mt-6 grid gap-4" onSubmit={submit}>
          {error && <Alert tone="critical">{error}</Alert>}
          <div>
            <label htmlFor="email" className="label">Email</label>
            <input
              id="email"
              type="email"
              className="input"
              autoComplete="username"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-primary h-10 w-full" disabled={busy}>
            {busy && <Spinner />} Send reset link
          </button>
        </form>
      )}
    </div>
  );
}
