import { cookies } from "next/headers";
import { dictionaries } from "@/i18n/dictionaries";
import { LOCALE_COOKIE, parseLocale } from "@/i18n/locale";

export async function getI18n() {
  const locale = parseLocale((await cookies()).get(LOCALE_COOKIE)?.value);
  return { locale, dictionary: dictionaries[locale] };
}
