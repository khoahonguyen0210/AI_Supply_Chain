"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { LoginForm } from "@/components/LoginForm";
import { Logo } from "@/components/Logo";
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

const LANDING_LINKS: { href: string; label: string }[] = [
  { href: "#how", label: "How it works" },
  { href: "#results", label: "Results" },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, ready, signOut } = useAuth();

  return (
    <>
      <header className="shell-header">
        <div className="shell-header-inner">
          <Link href="/" className="shell-title" aria-label="Supply Chain Planner home">
            <Logo />
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
                    {user.displayName} <span className="user-role">({humanize(user.role)})</span>
                  </span>
                </span>
                <button type="button" onClick={signOut}>
                  Sign out
                </button>
              </div>
            </>
          ) : ready ? (
            <nav className="shell-nav" aria-label="Sections">
              {LANDING_LINKS.map((item) => (
                <a key={item.href} href={item.href}>
                  {item.label}
                </a>
              ))}
              <a className="nav-cta" href="#sign-in">
                Sign in <span aria-hidden="true">→</span>
              </a>
            </nav>
          ) : null}
        </div>
      </header>
      <main className={user ? "shell-main" : "shell-main shell-main-wide"}>
        {!ready ? <p role="status">Loading…</p> : user ? children : <LoginForm />}
      </main>
      <footer className="shell-footer">
        <div className="footer-inner">
          <Logo />
          <p>Forecasts, purchase plans and approvals. Sample data only.</p>
          <p className="small">© 2026 Supply Chain Planner</p>
        </div>
      </footer>
    </>
  );
}
