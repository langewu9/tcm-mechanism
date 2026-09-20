"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";

export function LogoutButton() {
  const router = useRouter();
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }
  return (
    <button className="icon-button" onClick={logout} title="退出登录" aria-label="退出登录">
      <LogOut size={16} />
    </button>
  );
}
