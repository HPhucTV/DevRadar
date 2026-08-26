import { CvMatchPanel } from "@/components/cv-match-panel";
import { getI18n } from "@/i18n/server";

export default async function CvMatchPage() {
  const { dictionary } = await getI18n();
  return (
    <>
      <section className="route-header route-header--compact">
        <p className="route-label">{dictionary.cv.pageEyebrow}</p>
        <h1>{dictionary.cv.pageTitle}</h1>
        <p>{dictionary.cv.pageBody}</p>
      </section>
      <CvMatchPanel />
    </>
  );
}
