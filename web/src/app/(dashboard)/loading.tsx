"use client";
import { useI18n } from "@/i18n/locale-provider";
export default function Loading() { const { dictionary } = useI18n(); return <section className="route-panel loading-state" aria-busy="true"><p className="eyebrow">{dictionary.loading.eyebrow}</p><h1>{dictionary.loading.title}</h1><p>{dictionary.loading.body}</p></section>; }
