"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { LoginForm } from "@/components/LoginForm";
import { humanize } from "@/lib/format";
import { useAuth } from "@/lib/session";

const NAV_ITEMS: { href: string; label: string; roles?: string[] }[] = [
  { href: "/", label: "Overview" },
  { href: "/workspace", label: "Plan builder" },
  { href: "/copilot", label: "Assistant" },
  { href: "/approvals", label: "Approvals" },
  { href: "/documents", label: "Documents" },
  { href: "/operations", label: "Monitoring", roles: ["admin"] },
  { href: "/status", label: "Status" },
];

/** Sections of the sign-in page, linked from the bar before anyone is signed in. */
const LANDING_LINKS: { href: string; label: string }[] = [
  { href: "#how", label: "How it works" },
  { href: "#features", label: "Features" },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/** Page frame; shows only the sign-in page until someone signs in. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, ready, signOut } = useAuth();

  return (
    <>
      <header className="shell-header">
        <Link href="/" className="shell-title">
          AI Supply Chain Planner
        </Link>
        {user ? (
          <>
            <nav className="shell-nav" aria-label="Primary">
              {NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(user.role)).map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={isActive(pathname, item.href) ? "page" : undefined}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="session-picker">
              <span className="user-chip">
                <span className="avatar" aria-hidden="true">
                  {user.displayName.slice(0, 1)}
                </span>
                <span>
                  {user.displayName} <span className="muted">({humanize(user.role)})</span>
                </span>
              </span>
              <button type="button" onClick={signOut}>
                Sign out
              </button>
            </div>
          </>
        ) : ready ? (
          <>
            <nav className="shell-nav" aria-label="Sections">
              {LANDING_LINKS.map((item) => (
                <a key={item.href} href={item.href}>
                  {item.label}
                </a>
              ))}
            </nav>
            <a className="button-solid" href="#sign-in">
              Sign in
            </a>
          </>
        ) : null}
      </header>
      <div className="backdrop" aria-hidden="true" />
      <main className="shell-main">
        {!ready ? <p role="status">Loading…</p> : user ? children : <LoginForm />}
      </main>
    </>
  );
}
