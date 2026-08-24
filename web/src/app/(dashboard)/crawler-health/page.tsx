import { IngestionConsole } from "@/components/ingestion-console";
import { getI18n } from "@/i18n/server";

export default async function CrawlerHealthPage() { const { dictionary } = await getI18n(); return <><section className="page-intro crawler-intro"><p className="eyebrow">{dictionary.crawler.pageEyebrow}</p><h1>{dictionary.crawler.pageTitle}</h1><p>{dictionary.crawler.pageBody}</p></section><IngestionConsole /></>; }
