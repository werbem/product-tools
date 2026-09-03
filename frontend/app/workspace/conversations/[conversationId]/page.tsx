import { ConversationPageContent } from "@/components/workspace/conversation-page-content";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  return <ConversationPageContent conversationId={conversationId} />;
}
