"use client";

import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function DeleteButton({ endpoint, label = "删除" }: { endpoint: string; label?: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function remove() {
    if (!confirm("确认删除？")) return;
    setLoading(true);
    await fetch(endpoint, { method: "DELETE" });
    setLoading(false);
    router.refresh();
  }

  return (
    <button className="btn btn-secondary px-2 py-1 text-xs text-cinnabar" onClick={remove} disabled={loading} title={label}>
      <Trash2 size={14} />
      {loading ? "处理中" : label}
    </button>
  );
}
