import { ApiIntegrationConsole } from "@/components/ApiIntegrationConsole";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { PlugZap } from "lucide-react";
import { requireUser } from "@/lib/auth";

export const runtime = "nodejs";

export default async function ApiIntegrationPage() {
  const user = await requireUser();
  return (
    <AppShell user={user}>
      <PageHeader eyebrow="Integration health" title="API 接入监测" description="集中验证 Next.js、FastAPI、ChEMBL、本地模型与 AI Scientist 的真实调用链路。" icon={PlugZap} action={<span className="status-badge status-success">管理员功能</span>} />
      <ApiIntegrationConsole />
    </AppShell>
  );
}
