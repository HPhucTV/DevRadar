import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = { title: { default: "DevRadar", template: "%s | DevRadar" }, description: "Evidence-first job market intelligence for Vietnam IT roles." };
export default function RootLayout({ children }: { children: ReactNode }) { return <html lang="vi"><body>{children}</body></html>; }
