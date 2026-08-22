import Link from "next/link";
import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return <main className="auth-page"><div className="page-intro"><p className="eyebrow">DevRadar access</p><h1>Keep private work private.</h1><p>Use the authenticated session to manage CV matching and alerts. Public job browsing remains separate from owner data.</p></div><LoginForm /><p className="field-help"><Link href="/">Back to the dashboard</Link></p></main>;
}
