import { FileHeart, Stethoscope } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { CaseForm } from "@/components/CaseForm";
import { DeleteButton } from "@/components/DeleteButton";
import { requireUser } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

export default async function CasesPage() {
  const user = await requireUser();
  const items = await prisma.medicalCase.findMany({
    where: user.role === "ADMIN" ? {} : { ownerId: user.id },
    orderBy: { createdAt: "desc" }
  });
  return (
    <AppShell user={user}>
      <PageHeader eyebrow="Medical cases" title="结构化医案库" description="沉淀症状、舌脉、诊断与来源，为证候和网络药理分析提供上下文。" icon={FileHeart} action={<span className="status-badge status-success">{items.length} 条医案</span>} />
      <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
        <CaseForm />
        <section className="space-y-4">
          {items.map((item) => (
            <article key={item.id} className="case-record panel p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-black">{item.title}</h2>
                  <p className="mt-2 text-sm leading-6 text-ink/65">{item.symptoms}</p>
                </div>
                <DeleteButton endpoint={`/api/cases/${item.id}`} />
              </div>
              <div className="case-record-meta">
                <p><span>舌脉</span>{item.tonguePulse || "未填写"}</p>
                <p><span>诊断</span>{item.diagnosis || "未填写"}</p>
                <p><span>来源</span>{item.source || "未填写"}</p>
              </div>
            </article>
          ))}
          {!items.length ? <div className="panel empty-state"><Stethoscope size={26} /><strong>暂无医案</strong><p>录入第一条医案后，可直接在智能分析中选择并生成证候到通路的证据链。</p></div> : null}
        </section>
      </div>
    </AppShell>
  );
}
