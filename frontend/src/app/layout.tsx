import type { Metadata } from "next";
import { Geist_Mono, Manrope, Ubuntu } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import { SessionProvider } from "@/lib/session";
import "./globals.css";

// Ubuntu for headings (rounded, geometric), Manrope for reading text, Geist Mono for ids and numbers.
const display = Ubuntu({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

const body = Manrope({
  variable: "--font-body",
  subsets: ["latin"],
});

const mono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: { default: "AI Supply Chain Platform", template: "%s | AI Supply Chain Platform" },
  description: "AI Supply Chain Decision Intelligence Platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        <SessionProvider>
          <AppShell>{children}</AppShell>
        </SessionProvider>
      </body>
    </html>
  );
}
