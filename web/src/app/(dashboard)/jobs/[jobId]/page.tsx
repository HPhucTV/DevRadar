import { RoutePlaceholder } from "@/components/route-placeholder";
export default async function JobDetailPage({ params }: { params: Promise<{ jobId: string }> }) { const { jobId } = await params; return <RoutePlaceholder context={`Requested job ID: ${jobId}`} routeId="job-detail" />; }
