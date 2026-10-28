import { AppShell } from "@/components/AppShell";
import { ResearchWorkbench } from "@/components/ResearchWorkbench";
import { requireUser } from "@/lib/auth";

export const runtime = "nodejs";

export default async function ResearchPage() {
  const user = await requireUser();
  return <AppShell user={user}><ResearchWorkbench /></AppShell>;
}
