export const LOCALE_COOKIE = "devradar_locale";
export type Locale = "vi" | "en";

export function parseLocale(value: string | null | undefined): Locale {
  return value === "en" ? "en" : "vi";
}

export function localeTag(locale: Locale): "vi-VN" | "en-US" {
  return locale === "vi" ? "vi-VN" : "en-US";
}

export function formatDate(
  value: string | Date,
  locale: Locale,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" },
): string {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat(localeTag(locale), options).format(date);
}

export function formatNumber(value: number, locale: Locale): string {
  return new Intl.NumberFormat(localeTag(locale)).format(value);
}

export function formatPercent(value: number, locale: Locale, fractionDigits = 1): string {
  return new Intl.NumberFormat(localeTag(locale), {
    style: "percent",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

export function interpolate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{([A-Za-z0-9_]+)\}/g, (match, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : match,
  );
}
