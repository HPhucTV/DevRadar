"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { useI18n } from "@/i18n/locale-provider";
import { LOCALE_COOKIE, type Locale } from "@/i18n/locale";

export function LanguageSwitcher() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const { locale, dictionary } = useI18n();

  function selectLocale(next: Locale) {
    if (next === locale) return;
    document.cookie = `${LOCALE_COOKIE}=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
    startTransition(() => router.refresh());
  }

  return (
    <div className="language-switcher" aria-label={dictionary.locale.label} role="group">
      <button
        type="button"
        aria-label={dictionary.locale.vietnamese}
        aria-pressed={locale === "vi"}
        disabled={pending}
        onClick={() => selectLocale("vi")}
      >
        VI
      </button>
      <span aria-hidden="true">|</span>
      <button
        type="button"
        aria-label={dictionary.locale.english}
        aria-pressed={locale === "en"}
        disabled={pending}
        onClick={() => selectLocale("en")}
      >
        EN
      </button>
    </div>
  );
}
