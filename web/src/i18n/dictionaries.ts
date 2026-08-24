import messages from "@/i18n/dictionaries.json";
import type { Locale } from "@/i18n/locale";

export type Dictionary = typeof messages.vi;
const english: Dictionary = messages.en;

export const dictionaries: Record<Locale, Dictionary> = {
  vi: messages.vi,
  en: english,
};
