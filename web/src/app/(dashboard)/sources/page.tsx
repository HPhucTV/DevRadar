import { CustomSourcePanel } from "@/components/custom-source-panel";

export default function CustomSourcesPage() {
  return (
    <>
      <section className="page-intro">
        <p className="eyebrow">Owner-local and protected</p>
        <h1>Custom sources</h1>
        <p>Save a bounded URL, verify its fields, then schedule a crawl. Access challenges stop the profile for review.</p>
      </section>
      <CustomSourcePanel />
    </>
  );
}
