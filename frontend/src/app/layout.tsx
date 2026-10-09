import type { Metadata } from "next";

import "@fontsource/montserrat/400.css";
import "@fontsource/montserrat/500.css";
import "@fontsource/montserrat/700.css";
import "./globals.css";

import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "PPE safety", template: "%s · PPE safety" },
  description: "Solar Smart Factory PPE compliance monitoring",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <body className="grid-field min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
