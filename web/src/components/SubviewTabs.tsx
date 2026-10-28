import { createContext, useContext, useId, type ReactNode } from "react";

const SubviewVisibilityContext = createContext(true);
export function useSubviewVisible() { return useContext(SubviewVisibilityContext); }

export type Subview = { key: string; label: string; content: ReactNode };

export function nextSubview(keys: string[], current: string, key: string) {
  const index = Math.max(0, keys.indexOf(current));
  if (key === "Home") return keys[0];
  if (key === "End") return keys.at(-1);
  if (key === "ArrowRight") return keys[(index + 1) % keys.length];
  if (key === "ArrowLeft") return keys[(index - 1 + keys.length) % keys.length];
  return undefined;
}

/** Keep result subpages mounted for polling/state; chart viewers mount only the selected image. */
export function SubviewTabs({ label, views, value, onChange, keepMounted = false }: {
  label: string; views: Subview[]; value: string; onChange: (key: string) => void; keepMounted?: boolean;
}) {
  const id = useId();
  const parentVisible = useSubviewVisible();
  const active = views.some(view => view.key === value) ? value : views[0]?.key;
  return <div className="subview-workspace">
    <div className="subview-tabs" role="tablist" aria-label={label}>
      {views.map(view => <button key={view.key} id={`${id}-tab-${view.key}`} type="button" role="tab"
        className="subview-tab" aria-selected={view.key === active} aria-controls={`${id}-panel-${view.key}`}
        tabIndex={view.key === active ? 0 : -1} onClick={() => onChange(view.key)}
        onKeyDown={event => {
          const next = nextSubview(views.map(item => item.key), view.key, event.key);
          if (!next) return;
          event.preventDefault(); onChange(next);
          document.getElementById(`${id}-tab-${next}`)?.focus();
        }}>{view.label}</button>)}
    </div>
    {views.filter(view => keepMounted || view.key === active).map(view => <div key={view.key}
      id={`${id}-panel-${view.key}`} role="tabpanel" aria-labelledby={`${id}-tab-${view.key}`}
      className="subview-panel" hidden={view.key !== active} tabIndex={0}>
      <SubviewVisibilityContext.Provider value={parentVisible && view.key === active}>{view.content}</SubviewVisibilityContext.Provider>
    </div>)}
  </div>;
}
