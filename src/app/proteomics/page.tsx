import { Activity } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { ProteomicsWorkbench } from "@/components/ProteomicsWorkbench";
import { requireUser } from "@/lib/auth";

export const runtime = "nodejs";

export default async function ProteomicsPage() {
  const user = await requireUser();
  return (
    <AppShell user={user}>
      <PageHeader eyebrow="Proteomics analysis" title="差异蛋白组学分析" description="批量导入差异蛋白，筛选显著变化、生成本地蛋白-通路网络，并与网络药理学候选靶点进行交叉验证。" icon={Activity} action={<span className="status-badge status-success">本地安全模式</span>} />
      <ProteomicsWorkbench />
    </AppShell>
  );
}
