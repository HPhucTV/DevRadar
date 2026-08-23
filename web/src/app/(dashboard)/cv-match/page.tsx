import { CvMatchPanel } from "@/components/cv-match-panel";

export default function CvMatchPage() {
  return (
    <>
      <section className="page-intro cv-intro">
        <p className="eyebrow">Local and protected</p>
        <h1>See where your resume fits.</h1>
        <p>
          Upload a PDF or DOCX for a bounded local profile, then inspect the evidence behind each
          match. The original file and raw text are not kept by this page.
        </p>
      </section>
      <CvMatchPanel />
    </>
  );
}
