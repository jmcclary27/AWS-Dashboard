"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Space_Grotesk, IBM_Plex_Sans } from "next/font/google";
import type { ReactNode } from "react";

const displayFont = Space_Grotesk({ subsets: ["latin"], variable: "--font-display" });
const bodyFont = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-body" });

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/accounts", label: "Accounts" },
  { href: "/services", label: "Services" },
  { href: "/trends", label: "Trends" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/anomalies", label: "Anomalies" },
  { href: "/settings", label: "Settings" }
];

export function AppFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className={`${displayFont.variable} ${bodyFont.variable} min-h-screen font-[family-name:var(--font-body)] text-slate-900`}>
      <div className="data-grid min-h-screen">
        <div className="mx-auto flex min-h-screen max-w-7xl gap-6 px-4 py-5 sm:px-6 lg:px-8">
          <aside className="glass-panel hidden w-72 shrink-0 rounded-[28px] p-5 lg:flex lg:flex-col">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.32em] text-slate-500">AWS Portfolio</p>
              <h1 className="mt-3 font-[family-name:var(--font-display)] text-3xl font-semibold leading-tight">
                Collaboration
                <span className="gradient-text block">Cost Console</span>
              </h1>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                A demo-first FinOps command center built to grow from Compose into Kubernetes.
              </p>
            </div>

            <nav className="mt-8 space-y-2">
              {navItems.map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`block rounded-2xl px-4 py-3 text-sm transition ${
                      active
                        ? "bg-slate-900 text-white shadow-lg shadow-slate-900/15"
                        : "text-slate-600 hover:bg-white/80 hover:text-slate-900"
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>

            <div className="mt-auto rounded-3xl bg-slate-900 p-5 text-white">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Current Mode</p>
              <p className="mt-3 font-[family-name:var(--font-display)] text-xl">Demo Sync</p>
              <p className="mt-2 text-sm text-slate-300">
                90 days of seeded data, 14-day rolling refreshes, and future collector-ready API seams.
              </p>
            </div>
          </aside>

          <main className="flex-1 pb-10">
            <div className="glass-panel mb-6 flex items-center justify-between rounded-[28px] px-5 py-4 lg:hidden">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-slate-500">AWS Portfolio</p>
                <p className="font-[family-name:var(--font-display)] text-xl font-semibold">Cost Console</p>
              </div>
              <Link href="/dashboard" className="rounded-full bg-slate-900 px-4 py-2 text-sm text-white">
                Home
              </Link>
            </div>
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
