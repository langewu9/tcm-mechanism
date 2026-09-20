"use client";

import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function CaseForm() {
  const router = useRouter();
  const [message, setMessage] = useState("");

  async function submit(formData: FormData) {
    setMessage("");
    const payload = Object.fromEntries(formData);
    const response = await fetch("/api/cases", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      setMessage(data.error || "保存失败");
      return;
    }
    setMessage("医案已保存");
    router.refresh();
  }

  return (
    <form action={submit} className="panel space-y-3 p-5" aria-label="新增医案">
      <div><h2 className="section-title-sm">新增医案</h2><p className="section-help">录入结构化医案，后续可直接用于智能分析。</p></div>
      <label className="form-label">医案标题<input className="field mt-2" name="title" placeholder="例如：麦门冬汤干预肺纤维化研究医案" required /></label>
      <label className="form-label">患者信息<input className="field mt-2" name="patientInfo" placeholder="年龄、性别等脱敏信息" /></label>
      <label className="form-label">症状与主诉<textarea className="field mt-2 min-h-24" name="symptoms" placeholder="主要症状、现病史与伴随表现" required /></label>
      <label className="form-label">舌脉<input className="field mt-2" name="tonguePulse" placeholder="舌质、舌苔、脉象" /></label>
      <label className="form-label">诊断或证候<input className="field mt-2" name="diagnosis" placeholder="中医证候或西医诊断" /></label>
      <label className="form-label">资料来源<input className="field mt-2" name="source" placeholder="病例集、文献或门诊记录" /></label>
      {message ? <p className="notice-success" aria-live="polite">{message}</p> : null}
      <button className="btn btn-primary">
        <Save size={17} />
        保存医案
      </button>
    </form>
  );
}
