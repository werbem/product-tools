import { CollectionPageContent } from "@/components/workspace/collection-page-content";

export default async function CollectionPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const { taskId } = await params;
  return <CollectionPageContent taskId={taskId} />;
}
