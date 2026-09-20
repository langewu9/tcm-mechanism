"use client";

import { Bot, Send, X } from "lucide-react";
import { useState } from "react";

type Message = {
  role: "user" | "assistant";
  content: string;
};

export function AssistantWidget() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "本地 BianCang/Qwen 助手已接入。简单问题会快速回答，复杂医案和靶点分析会调用本地 7B 模型。"
    }
  ]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((items) => [...items, { role: "user", content: text }]);
    setLoading(true);
    try {
      const response = await fetch("/api/assistant", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text, maxTokens: 256, timeoutMs: 45000 })
      });
      const data = await response.json();
      setMessages((items) => [...items, { role: "assistant", content: data.answer || data.error || "模型暂无响应" }]);
    } catch (error) {
      setMessages((items) => [...items, { role: "assistant", content: error instanceof Error ? error.message : "请求失败" }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="assistant-float fixed right-5 z-30" aria-live="polite">
      {open ? (
        <section className="assistant-popover panel flex h-[560px] w-[360px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden" aria-label="远志本地模型助手">
          <div className="assistant-header">
            <div className="flex items-center gap-2 font-bold">
              <Bot size={18} />
              本地模型助手
            </div>
            <button className="assistant-close" onClick={() => setOpen(false)} title="关闭" aria-label="关闭助手">
              <X size={17} />
            </button>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={message.role === "user" ? "text-right" : "text-left"}>
                <div
                  className={`inline-block max-w-[88%] rounded-md px-3 py-2 text-sm leading-6 ${
                    message.role === "user" ? "assistant-message-user" : "assistant-message-model"
                  }`}
                >
                  {message.content}
                </div>
              </div>
            ))}
            {loading ? <p className="text-xs text-ink/50">正在处理；首次调用本地 7B 模型会慢一些...</p> : null}
          </div>
          <div className="border-t border-pine/10 p-3">
            <div className="flex gap-2">
              <input
                className="field min-w-0 flex-1"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") send();
                }}
                placeholder="输入医案、方药或靶点问题"
                aria-label="助手问题"
              />
              <button className="icon-button icon-button-primary" onClick={send} title="发送" aria-label="发送问题" disabled={loading || !input.trim()}>
                <Send size={17} />
              </button>
            </div>
          </div>
        </section>
      ) : (
        <button className="assistant-launcher" onClick={() => setOpen(true)} title="打开模型助手" aria-label="打开远志模型助手">
          <Bot size={22} />
        </button>
      )}
    </div>
  );
}
