import { Logo } from "@/components/brand/Logo";

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-[420px]">
        <div className="mb-8 flex flex-col items-center gap-4">
          <Logo width={150} />
          <p className="eyebrow-accent">PPE safety · Smart Factory</p>
        </div>
        <div className="panel-raised panel-brand p-7 sm:p-8">{children}</div>
        <p className="mt-6 text-center text-xs text-ink-3">Authorised Solar Group personnel only. Activity is logged.</p>
      </div>
    </main>
  );
}
