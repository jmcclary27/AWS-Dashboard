"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { formatCurrency, formatDateLabel } from "@/lib/format";

export function SpendLineChart({ data }: { data: Array<{ date: string; cost: number }> }) {
  return (
    <div className="h-[320px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid stroke="rgba(148, 163, 184, 0.15)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={formatDateLabel} tick={{ fill: "#64748b", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={(value) => formatCurrency(value, true)} tick={{ fill: "#64748b", fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip
            formatter={(value: number) => formatCurrency(value)}
            labelFormatter={(value) => formatDateLabel(value)}
            contentStyle={{ borderRadius: 18, border: "1px solid rgba(148, 163, 184, 0.16)" }}
          />
          <Line type="monotone" dataKey="cost" stroke="#1d4ed8" strokeWidth={3} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BreakdownBarChart({
  data,
  dataKey = "cost",
  labelKey = "label"
}: {
  data: Array<Record<string, string | number>>;
  dataKey?: string;
  labelKey?: string;
}) {
  return (
    <div className="h-[320px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 24 }}>
          <CartesianGrid stroke="rgba(148, 163, 184, 0.12)" horizontal={false} />
          <XAxis type="number" tickFormatter={(value) => formatCurrency(value, true)} tick={{ fill: "#64748b", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey={labelKey} width={120} tick={{ fill: "#334155", fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip formatter={(value: number) => formatCurrency(value)} contentStyle={{ borderRadius: 18, border: "1px solid rgba(148, 163, 184, 0.16)" }} />
          <Bar dataKey={dataKey} fill="#f97316" radius={[0, 12, 12, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function GroupTrendChart({ series }: { series: Array<{ date: string; group: string; cost: number }> }) {
  const groups = Array.from(new Set(series.map((item) => item.group))).slice(0, 6);
  const colors = ["#1d4ed8", "#0f766e", "#f97316", "#0ea5e9", "#9333ea", "#ef4444"];
  const grouped = new Map<string, Record<string, string | number>>();

  series.forEach((item) => {
    const existing = grouped.get(item.date) ?? { date: item.date };
    existing[item.group] = item.cost;
    grouped.set(item.date, existing);
  });

  const data = Array.from(grouped.values()).sort((left, right) =>
    String(left.date).localeCompare(String(right.date))
  );

  return (
    <div className="h-[360px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid stroke="rgba(148, 163, 184, 0.15)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={formatDateLabel} tick={{ fill: "#64748b", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={(value) => formatCurrency(value, true)} tick={{ fill: "#64748b", fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip formatter={(value: number) => formatCurrency(value)} labelFormatter={(value) => formatDateLabel(value)} contentStyle={{ borderRadius: 18, border: "1px solid rgba(148, 163, 184, 0.16)" }} />
          <Legend />
          {groups.map((group, index) => (
            <Line key={group} type="monotone" dataKey={group} stroke={colors[index % colors.length]} strokeWidth={2.4} dot={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

