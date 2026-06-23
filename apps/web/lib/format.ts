const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0
});

const compactCurrencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1
});

export function formatCurrency(value: number, compact = false): string {
  return compact ? compactCurrencyFormatter.format(value) : currencyFormatter.format(value);
}

export function formatPercent(value: number): string {
  const rounded = Number.isFinite(value) ? value : 0;
  return `${rounded >= 0 ? "+" : ""}${rounded.toFixed(1)}%`;
}

export function formatDateLabel(value: string): string {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric"
  });
}

export function formatDateTimeLabel(value: string | null): string {
  if (!value) {
    return "Never";
  }

  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

