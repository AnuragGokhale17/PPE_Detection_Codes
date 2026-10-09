import { Check, Circle } from "lucide-react";

// Mirrors check_password_policy in backend/app/core/security.py
const RULES: Array<[string, (p: string) => boolean]> = [
  ["At least 14 characters", (p) => p.length >= 14],
  ["A lowercase letter", (p) => /[a-z]/.test(p)],
  ["An uppercase letter", (p) => /[A-Z]/.test(p)],
  ["A number", (p) => /\d/.test(p)],
  ["A special character  ! @ # $ % ^ & * ( ) , . ? : { } | < >", (p) => /[!@#$%^&*(),.?:{}|<>]/.test(p)],
];

export function passwordMeetsPolicy(p: string) {
  return RULES.every(([, test]) => test(p));
}

export function PasswordRules({ password }: { password: string }) {
  return (
    <ul className="grid gap-1 text-xs text-ink-3" aria-label="Password requirements">
      {RULES.map(([label, test]) => {
        const ok = test(password);
        return (
          <li key={label} className={`flex items-center gap-2 ${ok ? "text-ok" : ""}`}>
            {ok ? <Check className="size-3.5" aria-hidden /> : <Circle className="size-3" aria-hidden />}
            <span>{label}</span>
            <span className="sr-only">{ok ? "met" : "not met"}</span>
          </li>
        );
      })}
    </ul>
  );
}
