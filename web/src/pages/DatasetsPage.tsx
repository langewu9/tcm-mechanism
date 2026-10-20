import { useEffect, useRef, useState, type FormEvent } from "react";
import { Database, Download, FileSpreadsheet, Archive, RotateCcw, Upload } from "lucide-react";
import { deleteDataset, getDatasets, restoreDataset, uploadDataset, type DatasetPage, type ResearchDataset } from "../api/datasets";
import { ApiError, apiRequestBlob } from "../api/client";
import { useConfirmation } from "../components/ConfirmationDialog";
import { datasetUploadErrorMessage } from "../utils/validation-errors";

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DatasetProvenance({ item }: { item: ResearchDataset }) {
  return <details className="mt-2 whitespace-normal text-xs font-normal">
    <summary className="cursor-pointer font-bold text-cinnabar">来源与校验信息</summary>
    {item.description && <p className="dataset-description">{item.description}</p>}
    <dl className="dataset-provenance">
      <div><dt>原始文件</dt><dd>{item.original_filename || "无文件"}</dd></div>
      <div><dt>大小</dt><dd>{formatBytes(item.byte_size)}（{item.byte_size.toLocaleString("zh-CN")} 字节）</dd></div>
      <div><dt>提交研究者</dt><dd>{item.owner_username}（#{item.owner_id}）</dd></div>
      <div><dt>导入时间</dt><dd><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("zh-CN")}</time></dd></div>
      <div className="col-span-full"><dt>SHA-256</dt><dd>{item.content_sha256 || "—"}</dd></div>
    </dl>
  </details>;
}

export function DatasetsPage() {
  const { confirm, confirmation } = useConfirmation();
  const [page, setPage] = useState<DatasetPage | null>(null);
  const [archived, setArchived] = useState(false);
  const [pageNumber, setPageNumber] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<{ text: string; failed: boolean } | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(false);
  const requestSequence = useRef(0);
  const mutationInFlight = useRef(false);
  const downloadInFlight = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, []);

  useEffect(() => {
    const sequence = ++requestSequence.current;
    let active = true;
    const isCurrent = () => active && mounted.current && sequence === requestSequence.current;
    setLoading(true);
    setListError(null);
    setPage(null);
    void getDatasets(pageNumber, archived)
      .then((data) => { if (isCurrent()) setPage(data); })
      .catch((cause: unknown) => { if (isCurrent()) setListError(errorMessage(cause)); })
      .finally(() => { if (isCurrent()) setLoading(false); });
    return () => { active = false; };
  }, [pageNumber, refresh, archived]);

  function reloadDatasets(nextPage = pageNumber) {
    requestSequence.current += 1;
    setLoading(true);
    setListError(null);
    setPage(null);
    setPageNumber(nextPage);
    setRefresh((value) => value + 1);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    const formElement = event.currentTarget;
    setUploading(true);
    setUploadMessage(null);
    setError(null);
    setNotice(null);
    try {
      const item = await uploadDataset(new FormData(formElement));
      if (!mounted.current) return;
      formElement.reset();
      setUploadMessage({ text: `已导入 ${item.row_count.toLocaleString("zh-CN")} 行数据，原始文件及 SHA-256 校验值已保存。`, failed: false });
      setArchived(false);
      reloadDatasets(1);
    } catch (cause) {
      if (mounted.current) setUploadMessage({ text: datasetUploadErrorMessage(cause), failed: true });
    } finally {
      mutationInFlight.current = false;
      if (mounted.current) setUploading(false);
    }
  }

  async function removeDataset(item: ResearchDataset) {
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    if (!await confirm({
      title: item.archived_at ? "恢复数据集" : "归档数据集",
      description: item.archived_at ? `恢复数据集“${item.name}”到正常列表？` : `归档数据集“${item.name}”？原文件和分析结果将保留，已提交任务继续运行。`,
      confirmLabel: item.archived_at ? "确认恢复" : "确认归档",
    })) { mutationInFlight.current = false; return; }
    setDeletingId(item.id);
    setError(null);
    setNotice(null);
    try {
      if (item.archived_at) await restoreDataset(item.id);
      else await deleteDataset(item.id);
      if (!mounted.current) return;
      setNotice(item.archived_at ? "数据集已恢复。" : "数据集已归档，原文件、所属用户和分析记录均已保留。");
      reloadDatasets(pageNumber > 1 && page?.results.length === 1 ? pageNumber - 1 : pageNumber);
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause));
    } finally {
      mutationInFlight.current = false;
      if (mounted.current) setDeletingId(null);
    }
  }

  async function downloadDataset(item: ResearchDataset) {
    if (downloadInFlight.current) return;
    downloadInFlight.current = true;
    setDownloadingId(item.id);
    setError(null);
    try {
      const blob = await apiRequestBlob(`/api/v1/research/datasets/${item.id}/download/`);
      if (!mounted.current) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = item.original_filename || `dataset-${item.id}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause));
    } finally {
      downloadInFlight.current = false;
      if (mounted.current) setDownloadingId(null);
    }
  }

  const mutating = uploading || deletingId !== null;
  const count = loading ? "…" : page ? page.count.toLocaleString("zh-CN") : "—";

  return <>
    {confirmation}
    <div className="page-heading">
      <div className="page-heading-copy">
        <p className="page-kicker">Data assets</p>
        <div className="flex items-center gap-3">
          <span className="page-heading-icon"><Database size={20} /></span>
          <h1 className="page-title">研究数据资产</h1>
        </div>
        <p className="page-description">导入、追踪并管理用于检索与分析的 CSV、Excel 数据集。</p>
      </div>
      <div className="page-heading-action"><span className="status-badge status-success" aria-live="polite">{count} 个数据集</span></div>
    </div>

    {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
    {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}

    <div className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
      <form className="panel space-y-3 p-5" onSubmit={submit} aria-label="上传研究数据集">
        <div>
          <h2 className="text-lg font-black">上传数据集</h2>
          <p className="mt-1 text-sm text-ink/58">支持 CSV、TSV、XLS、XLSX，入库后可检索、预览和归档。</p>
        </div>
        <label className="form-label" htmlFor="dataset-name">数据集名称<input className="field mt-2" id="dataset-name" name="name" maxLength={200} placeholder="例如：麦门冬汤六味中药成分靶点数据" required disabled={uploading} /></label>
        <label className="form-label" htmlFor="dataset-description">数据说明<textarea className="field mt-2 min-h-20" id="dataset-description" name="description" placeholder="描述来源、字段含义与使用范围" disabled={uploading} /></label>
        <label className="form-label" htmlFor="dataset-file">选择文件<input className="field mt-2" id="dataset-file" name="file" type="file" accept=".csv,.tsv,.xls,.xlsx" required disabled={uploading} /></label>
        <p className="section-help">原始文件保存在服务器私有存储中，下载时校验访问权限；保留字段名、行数及前 5,000 行供后续检查。</p>
        {uploadMessage && <p className={uploadMessage.failed ? "notice-error" : "notice-success"} role={uploadMessage.failed ? "alert" : "status"}>{uploadMessage.text}</p>}
        <button className="btn btn-primary" type="submit" disabled={mutating}>
          <Upload size={17} />{uploading ? "导入中..." : "导入数据"}
        </button>
      </form>

      <section className="panel overflow-hidden" aria-labelledby="dataset-list-heading" aria-busy={loading}>
        <div className="panel-header"><div><h2 id="dataset-list-heading" className="section-title-sm">数据集列表</h2><p className="section-help">归档保留原文件与来源记录，可在已归档列表恢复。</p></div></div>
        <label className="form-label px-5 py-3">显示范围<select className="field mt-2" value={String(archived)} disabled={mutating} onChange={(event) => { requestSequence.current += 1; setPage(null); setLoading(true); setArchived(event.target.value === "true"); setPageNumber(1); }}><option value="false">使用中的数据集</option><option value="true">已归档的数据集</option></select></label>
        <div className="overflow-x-auto">
          <table className="data-table" aria-label="数据集列表">
            <thead><tr>
              <th className="py-2" scope="col">名称</th>
              <th scope="col">文件</th>
              <th scope="col">行数</th>
              <th scope="col">上传人</th>
              <th scope="col">导入时间</th>
              <th scope="col">操作</th>
            </tr></thead>
            <tbody className="divide-y divide-pine/10">
              {page?.results.map((item) => <tr key={item.id}>
                <td className="py-3 font-bold"><span title={item.name}>{item.name}</span><DatasetProvenance item={item} /></td>
                <td title={item.original_filename}>{item.original_filename || "无文件"}</td>
                <td>{item.row_count.toLocaleString("zh-CN")}</td>
                <td>{item.owner_username}</td>
                <td><time dateTime={item.created_at} title={new Date(item.created_at).toLocaleString("zh-CN")}>{new Date(item.created_at).toLocaleDateString("zh-CN")}</time></td>
                <td><div className="flex gap-2">
                  <button className="btn btn-secondary px-2 py-1 text-xs" type="button" onClick={() => void downloadDataset(item)} disabled={downloadingId !== null || deletingId === item.id} aria-label={`下载原始文件：${item.name}`} title="下载原始文件"><Download size={14} />{downloadingId === item.id ? "下载中…" : "下载"}</button>
                  <button className="btn btn-secondary px-2 py-1 text-xs text-cinnabar" type="button" onClick={() => void removeDataset(item)} disabled={mutating} aria-label={`${item.archived_at ? "恢复" : "归档"}数据集：${item.name}`} title={item.archived_at ? "恢复数据集" : "归档并保留原文件"}>{item.archived_at ? <RotateCcw size={14} /> : <Archive size={14} />}{deletingId === item.id ? "处理中" : item.archived_at ? "恢复" : "归档"}</button>
                </div></td>
              </tr>)}
            </tbody>
          </table>
        </div>
        {loading ? <div className="empty-state" role="status">正在读取数据集…</div>
          : listError ? <div className="empty-state" role="alert"><strong>数据集列表读取失败</strong><p>{listError}</p><button className="btn btn-secondary" type="button" onClick={() => reloadDatasets()} disabled={mutating}>重试</button></div>
          : page?.results.length === 0 ? <div className="empty-state"><FileSpreadsheet size={26} /><strong>{archived ? "暂无归档数据集" : "暂无数据集"}</strong><p>{archived ? "归档后的资料会显示在这里，原始文件继续保留。" : "从左侧导入第一份 CSV、TSV 或 Excel 文件，系统会记录数据行数和上传人。"}</p></div> : null}
        {page && page.count > 0 && <nav className="table-pager" aria-label="数据集分页">
          <span>第 {pageNumber} 页 · 共 {page.count.toLocaleString("zh-CN")} 个数据集</span>
          <div>
            <button type="button" disabled={!page.previous || loading || mutating} onClick={() => reloadDatasets(Math.max(1, pageNumber - 1))}>上一页</button>
            <button type="button" disabled={!page.next || loading || mutating} onClick={() => reloadDatasets(pageNumber + 1)}>下一页</button>
          </div>
        </nav>}
      </section>
    </div>
  </>;
}
