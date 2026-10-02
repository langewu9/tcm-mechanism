import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { ArrowLeft, Database, Download, LogOut, Trash2, Upload } from "lucide-react";
import { deleteDataset, getDatasets, uploadDataset, type DatasetPage, type ResearchDataset } from "../api/datasets";
import { logout, type Session } from "../api/auth";
import { ApiError } from "../api/client";

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DatasetsPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const navigate = useNavigate();
  const [page, setPage] = useState<DatasetPage | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try { setPage(await getDatasets(pageNumber)); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setLoading(false); }
  }, [pageNumber]);

  useEffect(() => { void loadDatasets(); }, [loadDatasets, refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const item = await uploadDataset(new FormData(formElement));
      formElement.reset();
      setNotice(`已保存“${item.name}”的原始文件，SHA-256 校验值已记录。`);
      if (pageNumber !== 1) setPageNumber(1);
      else setRefresh((value) => value + 1);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setUploading(false); }
  }

  async function removeDataset(item: ResearchDataset) {
    if (!window.confirm(`确定删除数据集“${item.name}”及其服务器原始文件吗？`)) return;
    setDeletingId(item.id);
    setError(null);
    setNotice(null);
    try {
      await deleteDataset(item.id);
      setNotice("数据集记录及其私有原始文件已删除。");
      if (pageNumber > 1 && page?.results.length === 1) setPageNumber((value) => value - 1);
      else setRefresh((value) => value + 1);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setDeletingId(null); }
  }

  async function signOut() {
    setError(null);
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页">
        <img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" />
        <span><strong>远志 AI Scientist</strong><small>研究者工作区</small></span>
      </Link>
      <nav className="workspace-module-nav" aria-label="研究模块"><Link to="/cases">医案管理</Link><Link to="/datasets" aria-current="page">研究数据集</Link><Link to="/proteomics">蛋白组学</Link><Link to="/network-pharmacology">网络药理</Link>{user.isSuperuser && <Link to="/admin/sources">数据源同步</Link>}</nav>
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span>
        <button className="btn btn-secondary" type="button" onClick={signOut}><LogOut size={16} />退出</button></div>
    </header>

    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Research datasets</p><h1 className="page-title">研究数据资产</h1>
        <p className="page-description">上传的原始文件保存在服务器私有存储中，并记录提交者、文件大小和 SHA-256 校验值。研究者只能访问自己的数据集。</p></div>
        <Link to="/cases" className="btn btn-secondary"><ArrowLeft size={16} />医案管理</Link>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}

      <div className="case-workspace-grid dataset-workspace-grid">
        <form className="panel case-form" onSubmit={submit} aria-label="上传研究数据集">
          <div className="panel-header"><div><h2 className="section-title-sm">上传数据集</h2><p className="section-help">保留原始文件，便于后续质量检查和分析复现。</p></div><span className="page-heading-icon"><Upload size={19} /></span></div>
          <div className="case-form-fields">
            <label className="form-label" htmlFor="dataset-name">数据集名称<input className="field" id="dataset-name" name="name" maxLength={200} placeholder="例如：肺纤维化差异蛋白数据" required /></label>
            <label className="form-label" htmlFor="dataset-description">数据说明<textarea className="field case-textarea case-textarea-short" id="dataset-description" name="description" placeholder="来源、字段含义、物种或实验分组等说明" /></label>
            <label className="form-label" htmlFor="dataset-file">选择文件<input className="field dataset-file-input" id="dataset-file" name="file" type="file" accept=".csv,.tsv,.xls,.xlsx" required /></label>
            <p className="section-help">支持 CSV、TSV、XLS、XLSX；大小上限由服务端配置。上传后保留原文件并计算 SHA-256，本阶段尚未解析表格或运行分析。</p>
          </div>
          <div className="case-form-footer"><p>请确认拥有上传和研究该资料的授权。</p><button className="btn btn-primary" type="submit" disabled={uploading}><Upload size={16} />{uploading ? "正在保存…" : "保存数据集"}</button></div>
        </form>

        <section className="case-list" aria-labelledby="dataset-list-heading">
          <div className="case-list-heading"><div><p className="page-kicker">Private data assets</p><h2 id="dataset-list-heading" className="section-title-sm">已保存数据集</h2></div>
            <span className="status-badge status-success">{page?.count ?? 0} 个数据集</span></div>
          {loading ? <div className="panel empty-state" role="status">正在读取数据集…</div>
            : page?.results.length ? <div className="dataset-list-items">{page.results.map((item) => <article key={item.id} className="dataset-record panel">
              <div className="case-record-top"><div><h3>{item.name}</h3><time dateTime={item.created_at}>上传于 {new Date(item.created_at).toLocaleString("zh-CN")}</time></div>
                <button className="icon-button case-delete" type="button" onClick={() => void removeDataset(item)} disabled={deletingId === item.id} aria-label={`删除数据集：${item.name}`} title="删除数据集及原始文件"><Trash2 size={17} /></button></div>
              {item.description && <p className="dataset-description">{item.description}</p>}
              <dl className="dataset-provenance"><div><dt>原始文件</dt><dd>{item.original_filename || "无文件"}</dd></div><div><dt>大小</dt><dd>{formatBytes(item.byte_size)}</dd></div>
                <div><dt>提交研究者</dt><dd>{item.owner_username}</dd></div><div><dt>SHA-256</dt><dd title={item.content_sha256}>{item.content_sha256.slice(0, 16)}…</dd></div></dl>
              <a className="btn btn-secondary dataset-download" href={`/api/v1/research/datasets/${item.id}/download/`}><Download size={15} />下载原始文件</a>
            </article>)}</div>
            : <div className="panel empty-state"><Database size={27} /><strong>暂无数据集</strong><p>上传第一份 CSV 或 Excel 文件后，这里会显示原文件信息、提交者与校验值。</p></div>}
          {page && page.count > 0 && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!page.previous || loading} onClick={() => setPageNumber((value) => Math.max(1, value - 1))}>上一页</button>
            <span>第 {pageNumber} 页</span><button className="btn btn-secondary" type="button" disabled={!page.next || loading} onClick={() => setPageNumber((value) => value + 1)}>下一页</button></div>}
        </section>
      </div>
    </div></div>
  </main>;
}
