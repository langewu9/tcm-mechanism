import { Bot } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { AssistantWorkspace } from "@/components/AssistantWorkspace";
import { PageHeader } from "@/components/PageHeader";
import { requireUser } from "@/lib/auth";

export const runtime = "nodejs";

export default async function AssistantPage() {
  const user = await requireUser();
  return (
    <AppShell user={user}>
      <PageHeader eyebrow="Local AI assistant" title="远志研究助手" description="围绕医案、方药、成分、靶点与通路进行本地优先的问答和研究推理。" icon={Bot} action={<span className="status-badge status-success">AI Scientist 已就绪</span>} />
      <AssistantWorkspace />
    </AppShell>
  );
}
