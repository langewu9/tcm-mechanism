// Table paging adapted from origin/main@078d374:src/components/ViewportPager.tsx.
import { useEffect, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export function PaginatedTable<T>({ rows, headers, rowKey, renderCells, label = "结果" }: {
  rows: T[]; headers: string[]; rowKey: (row: T, index: number) => string;
  renderCells: (row: T, index: number) => ReactNode; label?: string;
}) {
  const [pageSize, setPageSize] = useState(8);
  const [page, setPage] = useState(0);
  useEffect(() => {
    const update = () => setPageSize(window.innerHeight >= 1080 ? 14 : window.innerHeight >= 900 ? 11 : window.innerHeight >= 760 ? 8 : 6);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  useEffect(() => setPage(0), [rows, pageSize]);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const start = safePage * pageSize;
  const visible = rows.slice(start, start + pageSize);
  return <section aria-label={label}>
    <div className="table-scroll"><table className="data-table" aria-label={label}>
      <thead><tr>{headers.map((header) => <th key={header} scope="col">{header}</th>)}</tr></thead>
      <tbody>{visible.length ? visible.map((row, index) => <tr key={rowKey(row, start + index)}>{renderCells(row, start + index)}</tr>) : <tr><td colSpan={headers.length}>暂无{label}记录。</td></tr>}</tbody>
    </table></div>
    {rows.length <= pageSize ? <p className="table-pager-summary">共 {rows.length} 条{label}</p> : <nav className="table-pager" aria-label={`${label}分页`}>
      <span>{start + 1}-{Math.min(rows.length, start + pageSize)} / {rows.length}</span>
      <div>
        <button type="button" aria-label={`${label}上一页`} disabled={safePage === 0} onClick={() => setPage(safePage - 1)}><ChevronLeft size={15} /></button>
        {Array.from({ length: pageCount }, (_, index) => index).slice(Math.max(0, safePage - 2), Math.min(pageCount, safePage + 3)).map((index) => <button type="button" key={index} className={index === safePage ? "is-active" : ""} aria-current={index === safePage ? "page" : undefined} onClick={() => setPage(index)}>{index + 1}</button>)}
        <button type="button" aria-label={`${label}下一页`} disabled={safePage === pageCount - 1} onClick={() => setPage(safePage + 1)}><ChevronRight size={15} /></button>
      </div>
    </nav>}
  </section>;
}
