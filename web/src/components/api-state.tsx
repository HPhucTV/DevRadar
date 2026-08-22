import type { ApiFailure } from "@/lib/api";

export function ApiErrorState({ error }: { error: ApiFailure }) { return <div className="api-state error-state" role="alert"><strong>Data unavailable</strong><p>{error.message}</p><small>{error.code} · HTTP {error.status}</small></div>; }
export function EmptyState({ message }: { message: string }) { return <div className="api-state empty-state"><strong>No data yet</strong><p>{message}</p></div>; }
export function Metric({ label, value, note }: { label: string; value: string | number; note?: string }) { return <div className="metric"><span>{label}</span><strong>{value}</strong>{note ? <small>{note}</small> : null}</div>; }
