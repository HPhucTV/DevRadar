import Link from "next/link";
import { redirect } from "next/navigation";
import { LoginForm } from "@/components/login-form";
import { getI18n } from "@/i18n/server";
import { localNoLoginEnabled } from "@/lib/deployment-mode";

export default async function LoginPage() {
  if (localNoLoginEnabled()) redirect("/");
  const { dictionary } = await getI18n();
  return <main className="auth-page"><div className="route-header"><p className="route-label">{dictionary.auth.accessEyebrow}</p><h1>{dictionary.auth.accessTitle}</h1><p>{dictionary.auth.accessBody}</p></div><LoginForm /><p className="field-help"><Link href="/">{dictionary.auth.back}</Link></p></main>;
}
