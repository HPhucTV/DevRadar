"use client";
import { useI18n } from "@/i18n/locale-provider";
export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) { const { dictionary } = useI18n(); return <section className="route-panel state-panel state-panel--error" role="alert"><p className="route-label">{dictionary.errors.unknownUiEyebrow}</p><h1>{dictionary.errors.unknownUiTitle}</h1><p>{dictionary.errors.unknownUiBody}</p><button type="button" onClick={() => reset()}>{dictionary.common.tryAgain}</button></section>; }
