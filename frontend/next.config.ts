import type { NextConfig } from "next";

// FastAPI origin. /api/* is proxied there so the session cookie stays same-origin.
// Read at build time: set API_ORIGIN before `next build` in each environment.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Self-contained server (node server.js) for the offline GPU server: no npm install there
  output: "standalone",
  // Only the logo uses next/image; skipping optimisation avoids shipping the native `sharp`
  // library, which would otherwise have to match the server's OS
  images: { unoptimized: true },
  // ...and keep the build OS's sharp binary out of the standalone bundle
  outputFileTracingExcludes: { "*": ["node_modules/@img/**", "node_modules/sharp/**"] },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
