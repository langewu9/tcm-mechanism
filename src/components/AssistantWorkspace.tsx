"use client";

import { Bot, CircleStop, RotateCcw, Send, Sparkles, UserRound } from "lucide-react";
import { useRef, useState } from "react";

type Message = {
  role: "user" | "assistant";
  content: string;
  source?: string;
};

const prompts = [
  "麦门冬汤由哪六味中药组成？各味药有哪些成分和作用靶点？",
  "麦门冬汤适合怎样开展肺纤维化网络药理学分析？",
  "请按方药、成分、靶点和通路分析麦门冬汤干预肺纤维化的研究证据链。"
];

const sourceLabels: Record<string, string> = {
  "quick-local": "快速回答",
  "local-knowledge": "本地知识库",
  "local-openai": "BianCang 模型",
  "fastapi-scientist": "AI Scientist",
  "timeout-fallback": "连接诊断"
};

export function AssistantWorkspace() {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      source: "quick-local",
      content: "你好，我是远志研究助手。检索类问题优先查本地知识库，复杂医案和机制问题会调用 BianCang/Qwen。"
    }
  ]);
  const controllerRef = useRef<AbortController | null>(null);

  async function send(value = input) {
    const text = value.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((items) => [...items, { role: "user", content: text }]);
    setLoading(true);
    const controller = new AbortController();
    controllerRef.current = controller;

    try {
      const response = await fetch("/api/assistant", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text, maxTokens: 384, timeoutMs: 60000 }),
        signal: controller.signal
      });
      const data = await response.json();
      setMessages((items) => [...items, {
        role: "assistant",
        source: data.source,
        content: data.answer || data.error || "模型没有返回可展示的内容。"
      }]);
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        setMessages((items) => [...items, { role: "assistant", source: "timeout-fallback", content: error instanceof Error ? error.message : "请求失败" }]);
      }
    } finally {
      setLoading(false);
      controllerRef.current = null;
    }
  }

  function stop() {
    controllerRef.current?.abort();
    setLoading(false);
  }

  function reset() {
    controllerRef.current?.abort();
    setMessages([{ role: "assistant", source: "quick-local", content: "会话已清空。可以继续输入新的医案、方药或靶点问题。" }]);
    setInput("");
    setLoading(false);
  }

  return (
    <div className="assistant-workspace">
      <aside className="assistant-prompts">
        <div>
          <p className="page-kicker">Prompt starters</p>
          <h3>从常见研究问题开始</h3>
          <p>示例问题会直接进入当前会话，也可以自行输入更完整的研究背景。</p>
        </div>
        <div className="assistant-prompt-list">
          {prompts.map((prompt) => (
            <button type="button" key={prompt} onClick={() => send(prompt)} disabled={loading}>
              <Sparkles size={15} />
              <span>{prompt}</span>
            </button>
          ))}
        </div>
        <div className="assistant-routing">
          <strong>智能路由</strong>
          <span>知识库检索 → 本地 7B 模型 → FastAPI AI Scientist</span>
        </div>
      </aside>

      <section className="assistant-thread panel" aria-label="助手会话">
        <div className="assistant-thread-header">
          <div><span className="assistant-status-dot" /><strong>远志研究助手</strong><small>本地优先 · 隐私友好</small></div>
          <button type="button" className="icon-button" onClick={reset} title="清空会话" aria-label="清空会话"><RotateCcw size={16} /></button>
        </div>

        <div className="assistant-thread-messages" aria-live="polite">
          {messages.map((message, index) => (
            <article className={`assistant-thread-message ${message.role}`} key={`${message.role}-${index}`}>
              <span className="assistant-thread-avatar" aria-hidden="true">{message.role === "assistant" ? <Bot size={17} /> : <UserRound size={17} />}</span>
              <div>
                <header><strong>{message.role === "assistant" ? "远志助手" : "你"}</strong>{message.source ? <span>{sourceLabels[message.source] || message.source}</span> : null}</header>
                <p>{message.content}</p>
              </div>
            </article>
          ))}
          {loading ? <article className="assistant-thread-message assistant is-loading"><span className="assistant-thread-avatar"><Bot size={17} /></span><div><header><strong>远志助手</strong><span>处理中</span></header><p>正在整理证据；复杂问题首次调用本地模型可能需要一些时间。</p></div></article> : null}
        </div>

        <form className="assistant-composer" onSubmit={(event) => { event.preventDefault(); send(); }}>
          <label htmlFor="assistant-input">研究问题</label>
          <textarea
            id="assistant-input"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            placeholder="输入医案症状、方药、成分、靶点或通路问题…"
            rows={3}
          />
          <div><span>Enter 发送，Shift + Enter 换行</span>{loading ? <button type="button" className="btn btn-secondary" onClick={stop}><CircleStop size={16} />停止</button> : <button className="btn btn-primary" disabled={!input.trim()}><Send size={16} />发送</button>}</div>
        </form>
      </section>
    </div>
  );
}
