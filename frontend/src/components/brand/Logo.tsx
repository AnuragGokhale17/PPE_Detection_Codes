import Image from "next/image";

// 600x136 source, 4.41:1. Floats unboxed on the surface per the brand rules.
export function Logo({ width = 132, className }: { width?: number; className?: string }) {
  return (
    <Image
      src="/brand/solar-logo.png"
      alt="Solar Group"
      width={width}
      height={Math.round(width / 4.41)}
      priority
      className={className}
    />
  );
}
