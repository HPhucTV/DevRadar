import type { Metadata } from "next";
import type { ReactNode } from "react";
import { LocaleProvider } from "@/i18n/locale-provider";
import { getI18n } from "@/i18n/server";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const { dictionary } = await getI18n();
  return {
    title: { default: "DevRadar", template: "%s | DevRadar" },
    description: dictionary.shell.description,
  };
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const { locale, dictionary } = await getI18n();
  return <html lang={locale}><body><LocaleProvider locale={locale} dictionary={dictionary}>{children}</LocaleProvider></body></html>;
}
