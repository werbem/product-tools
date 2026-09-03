import { ProjectDetailPageContent } from "@/components/workspace/project-detail-page-content";

export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return <ProjectDetailPageContent projectId={projectId} />;
}
