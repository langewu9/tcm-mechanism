import type { LucideIcon } from "lucide-react";

export function PageHeader({ eyebrow, title, description, icon: Icon, action }: { eyebrow: string; title: string; description: string; icon?: LucideIcon; action?: React.ReactNode }) {
  return (
    <div className="page-heading">
      <div className="page-heading-copy">
        <p className="page-kicker">{eyebrow}</p>
        <div className="flex items-center gap-3">
          {Icon ? <span className="page-heading-icon"><Icon size={20} /></span> : null}
          <h2 className="page-title">{title}</h2>
        </div>
        <p className="page-description">{description}</p>
      </div>
      {action ? <div className="page-heading-action">{action}</div> : null}
    </div>
  );
}
