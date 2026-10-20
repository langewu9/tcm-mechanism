import { useCallback, useEffect, useId, useRef, useState } from "react";

type Confirmation = { title: string; description: string; confirmLabel: string };

function ConfirmationDialog({ prompt, onDecision }: { prompt: Confirmation; onDecision: (confirmed: boolean) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const element = dialog.current;
    const previousFocus = document.activeElement;
    element?.showModal();
    cancel.current?.focus();
    return () => {
      if (element?.open) element.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);
  return <dialog ref={dialog} className="panel m-auto w-[28rem] max-w-[calc(100vw-2rem)] p-6 backdrop:bg-black/40"
    aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={(event) => { event.preventDefault(); onDecision(false); }}>
    <h2 id={titleId} className="section-title-sm">{prompt.title}</h2>
    <p id={descriptionId} className="my-4 break-words text-sm leading-7">{prompt.description}</p>
    <div className="flex justify-end gap-3">
      <button ref={cancel} className="btn btn-secondary" type="button" onClick={() => onDecision(false)}>取消</button>
      <button className="btn btn-primary" type="button" onClick={() => onDecision(true)}>{prompt.confirmLabel}</button>
    </div>
  </dialog>;
}

export function useConfirmation() {
  const [prompt, setPrompt] = useState<Confirmation | null>(null);
  const pending = useRef<((confirmed: boolean) => void) | null>(null);
  useEffect(() => () => { pending.current?.(false); pending.current = null; }, []);
  const confirm = useCallback((value: Confirmation) => new Promise<boolean>((resolve) => {
    if (pending.current) { resolve(false); return; }
    pending.current = resolve;
    setPrompt(value);
  }), []);
  function decide(confirmed: boolean) {
    const resolve = pending.current;
    pending.current = null;
    setPrompt(null);
    resolve?.(confirmed);
  }
  return { confirm, confirmation: prompt ? <ConfirmationDialog prompt={prompt} onDecision={decide} /> : null };
}
