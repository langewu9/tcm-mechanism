import { useEffect, useId, useMemo, useState } from "react";
import type { HerbEvidenceEntity, HerbEvidenceItem } from "../api/catalog";
import { PaginatedTable } from "./PaginatedTable";
import { SubviewTabs } from "./SubviewTabs";

export function uniqueEvidenceEntities(rows: HerbEvidenceEntity[]) {
  // Names are display values, not identity: same-name records retain their IDs.
  return [...new Map(rows.map(row => [row.id, row])).values()];
}

export function filterEvidenceEntities(rows: HerbEvidenceEntity[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter(row => [row.label, row.stableId, row.sourceSlug ?? "", row.sourceVersion ?? ""]
    .some(value => value.toLowerCase().includes(needle)));
}

export function EvidenceEntityDirectory({ rows, label }: { rows: HerbEvidenceEntity[]; label: string }) {
  const id = useId();
  const [query, setQuery] = useState("");
  useEffect(() => setQuery(""), [rows]);
  const filtered = useMemo(() => filterEvidenceEntities(rows, query), [rows, query]);
  return <div className="evidence-entity-directory">
    <div className="evidence-entity-toolbar">
      <label htmlFor={id}>筛选名称、ID 或来源
        <input id={id} className="field" type="search" value={query}
          aria-label={`筛选${label}`} placeholder="在本次返回记录中筛选"
          onChange={event => setQuery(event.target.value)} />
      </label>
      <p role="status">{filtered.length.toLocaleString()} / {rows.length.toLocaleString()} 条</p>
    </div>
    <PaginatedTable rows={filtered} label={label} headers={["序号", "名称", "来源库", "标识与版本"]}
      rowKey={row => String(row.id)} renderCells={(row, index) => <>
        <td>{index + 1}</td>
        <td className="evidence-entity-name">{row.label}</td>
        <td>{row.sourceSlug ?? "未登记来源"}</td>
        <td><details className="evidence-entity-provenance">
          <summary>查看 ID / 版本</summary>
          <dl><dt>数据库 ID</dt><dd>{row.id}</dd>
            <dt>稳定标识</dt><dd><code>{row.stableId}</code></dd>
            <dt>来源版本</dt><dd>{row.sourceVersion ?? "未登记版本"}</dd></dl>
        </details></td>
      </>} />
  </div>;
}

export function EvidenceEntityTables({ item }: { item: HerbEvidenceItem }) {
  const [active, setActive] = useState("compounds");
  useEffect(() => setActive("compounds"), [item]);
  const groups = useMemo(() => [
    { key: "matches", label: "匹配实体", rows: uniqueEvidenceEntities(item.matches) },
    { key: "herbs", label: "中药", rows: uniqueEvidenceEntities(item.herbs) },
    { key: "compounds", label: "成分", rows: uniqueEvidenceEntities(item.compounds) },
    { key: "targets", label: "靶点", rows: uniqueEvidenceEntities(item.targets) },
  ], [item]);
  return <section className="evidence-entity-tables" aria-label={`${item.query}实体目录`}>

    <SubviewTabs label={`${item.query}实体分类`} value={active} onChange={setActive}
      views={groups.map(group => ({ key: group.key,
        label: `${group.label}（${group.rows.length.toLocaleString()}）`,
        content: <EvidenceEntityDirectory key={group.key} rows={group.rows} label={`${item.query} · ${group.label}目录`} />,
      }))} />
  </section>;
}
