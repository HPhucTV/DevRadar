import { ApiErrorState } from "@/components/api-state";
import { interpolate } from "@/i18n/locale";
import { getI18n } from "@/i18n/server";
import { getPrivacy } from "@/lib/api";

export const dynamic = "force-dynamic";

function sourceLabel(sourceKey: string): string {
  return sourceKey === "geocomply-lever" ? "GeoComply / Lever" : sourceKey;
}

export default async function PrivacyPage() {
  const [{ dictionary }, result] = await Promise.all([getI18n(), getPrivacy()]);
  return <>
    <section className="page-intro">
      <p className="eyebrow">{dictionary.privacy.eyebrow}</p>
      <h1>{dictionary.privacy.title}</h1>
      <p>{dictionary.privacy.body}</p>
    </section>
    {result.kind === "error" ? <ApiErrorState error={result} /> : <>
      <section className="content-section policy-section policy-callout">
        <div className="section-heading"><div><p className="eyebrow">{dictionary.privacy.cvEyebrow}</p><h2>{dictionary.privacy.retention}</h2></div><span>{result.value.data.policyVersion}</span></div>
        <ul className="policy-list explanation-list">
          <li>{result.value.data.rawCvFileRetained ? dictionary.privacy.rawCvRetained : dictionary.privacy.rawCvNotRetained}</li>
          <li>{interpolate(dictionary.privacy.ttl, { hours: result.value.data.resumeProfileTtlHours })}</li>
          <li>{result.value.data.ownerDeletionSupported ? dictionary.privacy.deletion : dictionary.privacy.deletionDisabled}</li>
        </ul>
      </section>
      <section className="content-section policy-section">
        <div className="section-heading"><div><p className="eyebrow">{dictionary.privacy.aiEyebrow}</p><h2>{dictionary.privacy.deterministic}</h2></div></div>
        <ul className="policy-list explanation-list">
          <li>{result.value.data.deterministicExtractionFirst ? dictionary.privacy.deterministicFirst : dictionary.privacy.deterministicNotRequired}</li>
          <li>{result.value.data.externalLlmCvJdAllowed ? dictionary.privacy.externalAllowed : dictionary.privacy.externalBlocked}</li>
        </ul>
      </section>
      <section className="content-section policy-section">
        <div className="section-heading"><div><p className="eyebrow">{dictionary.privacy.sourceEyebrow}</p><h2>{dictionary.privacy.approvedOnly}</h2></div></div>
        <ul className="policy-list explanation-list">
          <li>{result.value.data.sourceAllowlistOnly ? dictionary.privacy.allowlistOnly : dictionary.privacy.allowlistDisabled}</li>
          <li>{dictionary.privacy.noBypass}</li>
          {result.value.data.permissionRequiredSourceKeys.map((sourceKey) => <li key={sourceKey}>{dictionary.privacy.sourceAccess}: {sourceLabel(sourceKey)} · permission_required</li>)}
        </ul>
      </section>
    </>}
  </>;
}
