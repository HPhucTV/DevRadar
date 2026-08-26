"use client";

import type { ApiFailure } from "@/lib/api";
import { useI18n } from "@/i18n/locale-provider";

export function ApiErrorState({ error }: { error: ApiFailure }) {
  const { dictionary } = useI18n();
  const known = dictionary.errors.codes as Record<string, string>;
  return <div className="state-panel state-panel--error" role="alert"><strong>{dictionary.common.dataUnavailable}</strong><p>{known[error.code] ?? error.message}</p><small>{error.code} · {dictionary.common.http} {error.status}</small></div>;
}
export function EmptyState({ message }: { message: string }) { const { dictionary } = useI18n(); return <div className="state-panel state-panel--empty"><strong>{dictionary.common.noDataYet}</strong><p>{message}</p></div>; }
export function Metric({ label, value, note }: { label: string; value: string | number; note?: string }) { return <div className="metric-card"><span>{label}</span><strong>{value}</strong>{note ? <small>{note}</small> : null}</div>; }
