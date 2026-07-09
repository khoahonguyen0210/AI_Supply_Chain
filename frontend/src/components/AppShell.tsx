import Link from "next/link";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/status", label: "System status" },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="shell-header">
        <span className="shell-title">AI Supply Chain Decision Intelligence</span>
        <nav className="shell-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="shell-main">{children}</main>
    </>
  );
}
