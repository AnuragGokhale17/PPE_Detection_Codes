"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";
import { api, ApiError } from "@/lib/api";
import { meQueryKey, safeNext, type Me } from "@/lib/auth";

type LoginResponse = { otp_required: boolean; email_hint: string; resend_in: number };

export function LoginFlow() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const next = safeNext(params.get("next"));

  const [step, setStep] = useState<"password" | "otp">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [hint, setHint] = useState("");
  const [resendIn, setResendIn] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(
    params.get("reason") === "expired" ? "Your session ended after 10 minutes of inactivity. Sign in again." : null,
  );
  const [busy, setBusy] = useState(false);
  const otpRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  useEffect(() => {
    if (step === "otp") otpRef.current?.focus();
  }, [step]);

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const res = await api<LoginResponse>("/auth/login", { method: "POST", json: { email, password } });
      setHint(res.email_hint);
      setResendIn(res.resend_in);
      setPassword("");
      setStep("otp");
    } catch (err) {
      if (err instanceof ApiError && err.code === "password_expired") {
        router.push(`/forgot-password?reason=expired&email=${encodeURIComponent(email)}`);
        return;
      }
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitOtp(code: string) {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const me = await api<Me>("/auth/verify-otp", { method: "POST", json: { otp: code } });
      queryClient.setQueryData(meQueryKey, me);
      router.replace(next);
    } catch (err) {
      setOtp("");
      if (err instanceof ApiError && err.code === "otp_session_expired") {
        setStep("password");
      }
      setError(err instanceof Error ? err.message : "Verification failed.");
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      const res = await api<{ resend_in: number }>("/auth/resend-otp", { method: "POST" });
      setResendIn(res.resend_in);
      setNotice(`A new code was sent to ${hint}.`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "otp_session_expired") setStep("password");
      setError(err instanceof Error ? err.message : "Could not resend the code.");
    }
  }

  if (step === "otp") {
    return (
      <div>
        <button type="button" className="btn btn-quiet btn-sm -ml-3 mb-4" onClick={() => { setStep("password"); setError(null); setNotice(null); }}>
          <ArrowLeft className="size-4" aria-hidden /> Back
        </button>
        <h1 className="text-xl font-bold">Check your email</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Enter the 6-digit code sent to <span className="font-medium text-ink">{hint}</span>. It expires in 5 minutes.
        </p>
        <form
          className="mt-6 grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (otp.length === 6) submitOtp(otp);
          }}
        >
          {error && <Alert tone="critical">{error}</Alert>}
          {notice && <Alert tone="info">{notice}</Alert>}
          <div>
            <label htmlFor="otp" className="label">Sign-in code</label>
            <input
              id="otp"
              ref={otpRef}
              className="input tabular h-12 text-center text-2xl font-bold tracking-[0.5em]"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              maxLength={6}
              value={otp}
              disabled={busy}
              onChange={(e) => {
                const v = e.target.value.replace(/\D/g, "").slice(0, 6);
                setOtp(v);
                if (v.length === 6) submitOtp(v);
              }}
            />
          </div>
          <button type="submit" className="btn btn-primary h-10 w-full" disabled={busy || otp.length !== 6}>
            {busy && <Spinner />} Verify and sign in
          </button>
          <p className="text-center text-xs text-ink-3">
            Didn&apos;t get it?{" "}
            {resendIn > 0 ? (
              <span className="tabular">Resend in {resendIn}s</span>
            ) : (
              <button type="button" className="font-bold text-accent-700 hover:underline" onClick={resend}>
                Send a new code
              </button>
            )}
          </p>
        </form>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-xl font-bold">Sign in</h1>
      <p className="mt-1.5 text-sm text-ink-2">Use your Solar Group email. We&apos;ll email you a one-time code.</p>
      <form className="mt-6 grid gap-4" onSubmit={submitPassword}>
        {error && <Alert tone="critical">{error}</Alert>}
        {notice && <Alert tone="info">{notice}</Alert>}
        <div>
          <label htmlFor="email" className="label">Email</label>
          <input
            id="email"
            type="email"
            className="input"
            autoComplete="username"
            placeholder="first.last@solargroup.com"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <div className="flex items-baseline justify-between">
            <label htmlFor="password" className="label">Password</label>
            <Link href={`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`} className="text-xs font-medium text-accent-700 hover:underline">
              Forgot password?
            </Link>
          </div>
          <input
            id="password"
            type="password"
            className="input"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-primary mt-1 h-10 w-full" disabled={busy}>
          {busy && <Spinner />} Continue
        </button>
      </form>
    </div>
  );
}
