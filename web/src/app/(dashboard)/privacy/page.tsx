import { ApiErrorState } from "@/components/api-state";
import { getPrivacy } from "@/lib/api";

export const dynamic = "force-dynamic";

function sourceLabel(sourceKey: string): string {
  return sourceKey === "geocomply-lever" ? "GeoComply / Lever" : sourceKey;
}

export default async function PrivacyPage() {
  const result = await getPrivacy();
  return <>
    <section className="page-intro">
      <p className="eyebrow">Privacy & source policy</p>
      <h1>Know what DevRadar keeps.</h1>
      <p>Policy facts below come from the running API contract, not from a browser-side guess or hidden configuration.</p>
    </section>
    {result.kind === "error" ? <ApiErrorState error={result} /> : <>
      <section className="content-section">
        <div className="section-heading"><div><p className="eyebrow">CV and owner data</p><h2>Retention and deletion</h2></div><span>{result.value.data.policyVersion}</span></div>
        <ul className="explanation-list">
          <li>{result.value.data.rawCvFileRetained ? "CV file retention is enabled by policy." : "CV file gốc không được giữ mặc định."}</li>
          <li>ResumeProfile được giữ tối đa {result.value.data.resumeProfileTtlHours} giờ.</li>
          <li>{result.value.data.ownerDeletionSupported ? "Owner có thể xóa profile; match và dữ liệu liên quan được cascade theo lifecycle." : "Owner deletion chưa được bật."}</li>
        </ul>
      </section>
      <section className="content-section">
        <div className="section-heading"><div><p className="eyebrow">AI boundary</p><h2>Deterministic before model</h2></div></div>
        <ul className="explanation-list">
          <li>{result.value.data.deterministicExtractionFirst ? "Structured data/parser chạy trước LLM fallback." : "Deterministic extraction không phải policy bắt buộc."}</li>
          <li>{result.value.data.externalLlmCvJdAllowed ? "CV/JD có thể được gửi tới external LLM theo cấu hình." : "Không gửi CV/JD tới external LLM theo policy hiện hành."}</li>
        </ul>
      </section>
      <section className="content-section">
        <div className="section-heading"><div><p className="eyebrow">Source policy</p><h2>Approved allow-list only</h2></div></div>
        <ul className="explanation-list">
          <li>{result.value.data.sourceAllowlistOnly ? "Crawler chỉ nhận source đã approved trong allow-list." : "Crawler policy không giới hạn allow-list."}</li>
          {result.value.data.permissionRequiredSourceKeys.map((sourceKey) => <li key={sourceKey}>{sourceLabel(sourceKey)}: permission required; không automated retrieval.</li>)}
        </ul>
      </section>
    </>}
  </>;
}
