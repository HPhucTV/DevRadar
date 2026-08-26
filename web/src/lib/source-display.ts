export type SourceDisplayInput = { name: string; url: string };

export function sourceDisplayName(source: SourceDisplayInput): string {
  const isCollector = /^Collector\s*·\s*/i.test(source.name);
  if (!isCollector) return source.name.slice(0, 48);
  const collector = source.name
    .replace(/^Collector\s*·\s*/i, "")
    .replace(/\s*\[[0-9a-f]{8}\]\s*$/i, "")
    .replace(/^www\./i, "")
    .trim();
  if (collector && collector.length <= 48) return collector;
  try { return new URL(source.url).hostname.replace(/^www\./i, ""); }
  catch { return source.name.slice(0, 48); }
}
