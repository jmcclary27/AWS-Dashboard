"use client";

import type { ReactNode } from "react";

import { formatCurrency, formatDateTimeLabel, formatPercent } from "@/lib/format";

export function PageHeader({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="glass-panel rounded-[32px] p-6 sm:p-8">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-slate-500">{eyebrow}</p>
          <h2 className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold leading-tight text-slate-950">
            {title}
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600">{description}</p>
        </div>
        {action ? <div>{action}</div> : null}
      </div>
    </div>
  );
}

export function StatCard({
  label,
  value,
  detail,
  accent = "blue"
}: {
  label: string;
  value: string;
  detail: string;
  accent?: "blue" | "orange" | "teal";
}) {
  const accentClasses = {
    blue: "from-blue-600/15 to-cyan-400/10 text-blue-700",
    orange: "from-orange-500/15 to-amber-300/10 text-orange-700",
    teal: "from-emerald-600/15 to-teal-300/10 text-teal-700"
  };

  return (
    <div className="glass-panel rounded-[28px] p-5">
      <div className={`inline-flex rounded-full bg-gradient-to-r px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${accentClasses[accent]}`}>
        {label}
      </div>
      <p className="mt-5 font-[family-name:var(--font-display)] text-4xl font-semibold text-slate-950">{value}</p>
      <p className="mt-2 text-sm leading-6 text-slate-600">{detail}</p>
    </div>
  );
}

export function Panel({
  title,
  subtitle,
  children
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="glass-panel rounded-[30px] p-5 sm:p-6">
      <div className="mb-5">
        <h3 className="font-[family-name:var(--font-display)] text-2xl font-semibold text-slate-950">{title}</h3>
        {subtitle ? <p className="mt-1 text-sm text-slate-600">{subtitle}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function StatusPill({ label }: { label: string }) {
  const lower = label.toLowerCase();
  const classes = lower.includes("success") || lower.includes("open")
    ? "bg-emerald-500/10 text-emerald-700"
    : lower.includes("high")
      ? "bg-orange-500/15 text-orange-700"
      : "bg-slate-900/8 text-slate-700";

  return <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${classes}`}>{label}</span>;
}

export function LoadingState({ label = "Loading dashboard data..." }: { label?: string }) {
  return (
    <div className="glass-panel rounded-[30px] p-10 text-center text-sm text-slate-500">
      <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" />
      <p className="mt-4">{label}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="glass-panel rounded-[30px] border border-red-200 p-8 text-sm text-red-700">
      {message}
    </div>
  );
}

export function MetricRow({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "good" | "warm" }) {
  const toneClass = tone === "good" ? "text-emerald-700" : tone === "warm" ? "text-orange-700" : "text-slate-700";
  return (
    <div className="flex items-center justify-between border-b border-slate-200/70 py-3 last:border-none">
      <span className="text-sm text-slate-500">{label}</span>
      <span className={`text-sm font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

export function SmallMeta({
  updatedAt,
  status
}: {
  updatedAt: string | null;
  status: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
      <span>{formatDateTimeLabel(updatedAt)}</span>
      <StatusPill label={status} />
    </div>
  );
}

export function RecommendationCard({
  title,
  summary,
  impact,
  savings,
  account,
  service
}: {
  title: string;
  summary: string;
  impact: string;
  savings: number;
  account?: string | null;
  service?: string | null;
}) {
  return (
    <div className="rounded-[24px] border border-slate-200/70 bg-white/70 p-5">
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-semibold text-slate-900">{title}</h4>
        <StatusPill label={impact} />
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">{summary}</p>
      <div className="mt-4 flex flex-wrap gap-2 text-xs uppercase tracking-[0.18em] text-slate-500">
        {account ? <span>{account}</span> : null}
        {service ? <span>{service}</span> : null}
      </div>
      <p className="mt-4 font-[family-name:var(--font-display)] text-2xl font-semibold text-slate-950">
        {formatCurrency(savings)}
      </p>
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Estimated monthly savings</p>
    </div>
  );
}

export function AnomalyCard({
  title,
  summary,
  severity,
  delta,
  account,
  detectedOn
}: {
  title: string;
  summary: string;
  severity: string;
  delta: number;
  account?: string | null;
  detectedOn: string;
}) {
  return (
    <div className="rounded-[24px] border border-slate-200/70 bg-white/70 p-5">
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-semibold text-slate-900">{title}</h4>
        <StatusPill label={severity} />
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">{summary}</p>
      <div className="mt-4 flex items-center justify-between text-sm">
        <span className="text-slate-500">{account ?? "Shared scope"}</span>
        <span className="font-semibold text-orange-700">{formatCurrency(delta)}</span>
      </div>
      <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-500">{new Date(detectedOn).toLocaleDateString()}</p>
    </div>
  );
}

export function AccountTableRow({
  account,
  onSync,
  showSyncAction = true
}: {
  account: {
    id: number;
    display_name: string;
    aws_account_id: string;
    enabled: boolean;
    current_30d_cost: number;
    forecast_total: number;
    unallocated_share_pct: number;
    last_sync_at: string | null;
    last_sync_status: string;
    membership_source: string;
    is_primary: boolean;
  };
  onSync: (accountId: number) => void;
  showSyncAction?: boolean;
}) {
  return (
    <tr className="border-b border-slate-200/70 text-sm last:border-none">
      <td className="py-4 pr-4">
        <p className="font-semibold text-slate-900">{account.display_name}</p>
        <p className="text-slate-500">{account.aws_account_id}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <StatusPill label={account.membership_source} />
          {account.is_primary ? <StatusPill label="primary" /> : null}
        </div>
      </td>
      <td className="py-4 pr-4">{formatCurrency(account.current_30d_cost)}</td>
      <td className="py-4 pr-4">{formatCurrency(account.forecast_total)}</td>
      <td className="py-4 pr-4">{formatPercent(account.unallocated_share_pct)}</td>
      <td className="py-4 pr-4">
        <SmallMeta updatedAt={account.last_sync_at} status={account.last_sync_status} />
      </td>
      <td className="py-4 text-right">
        {showSyncAction ? (
          <button
            onClick={() => onSync(account.id)}
            className="rounded-full bg-slate-900 px-4 py-2 text-sm text-white transition hover:bg-slate-700"
          >
            Sync
          </button>
        ) : (
          <span className="text-xs uppercase tracking-[0.18em] text-slate-500">connection sync</span>
        )}
      </td>
    </tr>
  );
}

export const uiHelpers = {
  formatCurrency,
  formatDateTimeLabel,
  formatPercent
};
