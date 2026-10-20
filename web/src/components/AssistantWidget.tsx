// Floating assistant shell ported from main; questions enter the existing evidence workbench.
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Send, X } from "lucide-react";

export function AssistantWidget() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const navigate = useNavigate();
  function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (!question) return;
    navigate("/assistant", { state: { draftQuestion: question } });
    setInput(""); setOpen(false);
  }
  return <div className="assistant-float restored-assistant-float" aria-live="polite">
    {open ? <section className="assistant-popover panel restored-assistant-popover" aria-label="远志本地模型助手">
      <div className="assistant-header"><div className="restored-assistant-heading"><Bot size={18} />本地模型助手</div>
        <button className="assistant-close" onClick={() => setOpen(false)} title="关闭" aria-label="关闭助手"><X size={17} /></button>
      </div>
      <div className="restored-assistant-messages"><div className="assistant-message-model restored-assistant-message">问题将带入助手工作台。请先选择本地目录证据；调用模型前需单独确认。</div></div>
      <form className="restored-assistant-input" onSubmit={send}>
        <input className="field" value={input} maxLength={2000} onChange={(event) => setInput(event.target.value)} placeholder="输入医案、方药或靶点问题" aria-label="助手问题" />
        <button className="icon-button icon-button-primary" title="前往助手工作台" aria-label="发送问题到助手工作台" disabled={!input.trim()}><Send size={17} /></button>
      </form>
    </section> : <button className="assistant-launcher" onClick={() => setOpen(true)} title="打开模型助手" aria-label="打开远志模型助手"><Bot size={22} /></button>}
  </div>;
}
