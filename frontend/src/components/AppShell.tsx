"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { DEV_USERS, useSession } from "@/lib/session";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/workspace", label: "Decision workspace" },
  { href: "/copilot", label: "Copilot" },
  { href: "/approvals", label: "Approvals" },
  { href: "/documents", label: "Documents" },
  { href: "/status", label: "System status" },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function SessionPicker() {
  const { user, signInAs } = useSession();
  return (
    <label className="session-picker">
      <span className="muted">Signed in as</span>
      <select value={user.userId} onChange={(e) => signInAs(e.target.value)}>
        {DEV_USERS.map((u) => (
          <option key={u.userId} value={u.userId}>
            {u.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <>
      <header className="shell-header">
        <span className="shell-title">AI Supply Chain Decision Intelligence</span>
        <nav className="shell-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(pathname, item.href) ? "page" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <SessionPicker />
      </header>
      <main className="shell-main">{children}</main>
    </>
  );
}
