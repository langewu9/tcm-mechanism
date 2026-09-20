"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

type PageItem = {
  id: string;
  label: string;
  description?: string;
  content: ReactNode;
};

export function useViewportPageSize() {
  const [pageSize, setPageSize] = useState(8);

  useEffect(() => {
    const update = () => {
      const height = window.innerHeight;
      setPageSize(height >= 1080 ? 14 : height >= 900 ? 11 : height >= 760 ? 8 : 6);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return pageSize;
}

export function TablePager({ total, page, pageSize, onPageChange, label = "结果" }: { total: number; page: number; pageSize: number; onPageChange: (page: number) => void; label?: string }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const first = total ? safePage * pageSize + 1 : 0;
  const last = Math.min(total, (safePage + 1) * pageSize);

  if (total <= pageSize) return <p className="table-pager-summary">共 {total} 条{label}</p>;

  return (
    <nav className="table-pager" aria-label={`${label}分页`}>
      <span>{first}-{last} / {total}</span>
      <div>
        <button type="button" aria-label="上一页" disabled={safePage === 0} onClick={() => onPageChange(safePage - 1)}><ChevronLeft size={15} /></button>
        {Array.from({ length: pageCount }, (_, index) => index).slice(Math.max(0, safePage - 2), Math.min(pageCount, safePage + 3)).map((index) => (
          <button type="button" key={index} className={index === safePage ? "is-active" : ""} aria-current={index === safePage ? "page" : undefined} onClick={() => onPageChange(index)}>{index + 1}</button>
        ))}
        <button type="button" aria-label="下一页" disabled={safePage >= pageCount - 1} onClick={() => onPageChange(safePage + 1)}><ChevronRight size={15} /></button>
      </div>
    </nav>
  );
}

export function useTablePager(total: number) {
  const pageSize = useViewportPageSize();
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount - 1);

  useEffect(() => setPage(0), [total, pageSize]);

  return {
    page: safePage,
    pageSize,
    visibleRange: [safePage * pageSize, (safePage + 1) * pageSize] as const,
    pager: <TablePager total={total} page={safePage} pageSize={pageSize} onPageChange={setPage} />
  };
}

export function PaginatedTable<T>({ rows, headers, rowKey, renderCells, label = "结果" }: { rows: T[]; headers: string[]; rowKey: (row: T, index: number) => string; renderCells: (row: T, index: number) => ReactNode; label?: string }) {
  const { visibleRange, pager } = useTablePager(rows.length);
  const visible = rows.slice(...visibleRange);
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
          <tbody>{visible.map((row, index) => <tr key={rowKey(row, index)}>{renderCells(row, index + visibleRange[0])}</tr>)}</tbody>
        </table>
      </div>
      {pager}
    </div>
  );
}

export function HorizontalPager({ pages, ariaLabel = "内容分页" }: { pages: PageItem[]; ariaLabel?: string }) {
  const [active, setActive] = useState(0);
  const pageCount = pages.length;
  const safeActive = Math.min(active, Math.max(pageCount - 1, 0));
  const activePage = pages[safeActive];

  useEffect(() => setActive(0), [pageCount]);

  const pageTitles = useMemo(() => pages.map((item) => item.label), [pages]);
  if (!activePage) return null;

  return (
    <section className="horizontal-pager" aria-label={ariaLabel}>
      <div className="horizontal-pager-tabs" role="tablist" aria-label={ariaLabel}>
        {pages.map((item, index) => (
          <button key={item.id} type="button" role="tab" aria-selected={index === safeActive} className={index === safeActive ? "is-active" : ""} onClick={() => setActive(index)}>
            <span>{String(index + 1).padStart(2, "0")}</span>{item.label}
          </button>
        ))}
      </div>
      <div className="horizontal-pager-viewport">
        <div className="horizontal-pager-track" style={{ transform: `translateX(-${safeActive * 100}%)` }}>
          {pages.map((item, index) => <div className="horizontal-pager-page" key={item.id} aria-hidden={index !== safeActive}>{item.content}</div>)}
        </div>
      </div>
      <div className="horizontal-pager-footer">
        <button type="button" onClick={() => setActive((current) => Math.max(0, current - 1))} disabled={safeActive === 0}><ChevronLeft size={16} />上一页</button>
        <span>{safeActive + 1} / {pageCount} · {pageTitles[safeActive]}</span>
        <button type="button" onClick={() => setActive((current) => Math.min(pageCount - 1, current + 1))} disabled={safeActive === pageCount - 1}>下一页<ChevronRight size={16} /></button>
      </div>
    </section>
  );
}
