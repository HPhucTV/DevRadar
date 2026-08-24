import { CvMatchPanel } from "@/components/cv-match-panel";
import { getI18n } from "@/i18n/server";

export default async function CvMatchPage() {
  const { dictionary } = await getI18n();
  return (
    <>
      <section className="page-intro cv-intro">
        <p className="eyebrow">{dictionary.cv.pageEyebrow}</p>
        <h1>{dictionary.cv.pageTitle}</h1>
        <p>{dictionary.cv.pageBody}</p>
      </section>
      <CvMatchPanel />
    </>
  );
}
