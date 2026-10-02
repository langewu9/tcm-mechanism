import { Network } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { NetworkPharmacologyWorkbench } from "@/components/NetworkPharmacologyWorkbench";
import { requireUser } from "@/lib/auth";

export const runtime = "nodejs";

export default async function VisualizationPage() {
  const user = await requireUser();

  return (
    <AppShell user={user}>
      <PageHeader eyebrow="Visual analytics" title="查询驱动网络药理图谱" description="围绕当前中药与疾病生成靶点交集、成分证据、通路分布、证据链网络和原始下载表。" icon={Network} action={<span className="status-badge status-success">所有图表随查询更新</span>} />

      <NetworkPharmacologyWorkbench />
    </AppShell>
  );
}
