"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { LoginForm } from "@/components/LoginForm";
import { humanize } from "@/lib/format";
import { useAuth } from "@/lib/session";

const NAV_ITEMS: { href: string; label: string; roles?: string[] }[] = [
  { href: "/", label: "Dashboard" },
  { href: "/workspace", label: "Decision workspace" },
  { href: "/copilot", label: "Copilot" },
  { href: "/approvals", label: "Approvals" },
  { href: "/documents", label: "Documents" },
  { href: "/operations", label: "Operations", roles: ["admin"] },
  { href: "/status", label: "System status" },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The frame around every page. Nothing but the sign-in form is shown until someone is signed in, so pages
 * never run without a user and never request data without a token.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, ready, signOut } = useAuth();

  return (
    <>
      <header className="shell-header">
        <span className="shell-title">AI Supply Chain Decision Intelligence</span>
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
              <span>
                {user.displayName} <span className="muted">({humanize(user.role)})</span>
              </span>
              <button type="button" onClick={signOut}>
                Sign out
              </button>
            </div>
          </>
        ) : null}
      </header>
      <main className="shell-main">
        {!ready ? <p role="status">Loading…</p> : user ? children : <LoginForm />}
      </main>
    </>
  );
}
