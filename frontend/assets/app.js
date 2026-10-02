const $ = (id) => document.getElementById(id);

const titles = {
  overview: ["总览驾驶舱", "以中医医案、药理数据库、ChEMBL 与文献证据生成可验证科学假设。"],
  scientist: ["AI Scientist 工作台", "从研究问题到标准化科学假设与实验设计的一键生成。"],
  qwen: ["千问接入", "配置阿里云百炼 OpenAI 兼容接口，为 AI Scientist 启用 Qwen 增强。"],
  disease: ["疾病-中药-靶点", "按疾病名称检索候选中药和疾病相关靶点。"],
  herb: ["中药-成分-靶点", "按中药名称整合五大中药药理数据库。"],
  component: ["成分检索", "按成分名称批量定位靶点与来源中药。"],
  tools: ["交集与比对", "用于网络药理学共同靶点计算和检测成分验证。"],
  chembl: ["ChEMBL 本地库", "连接 D:\\chembl\\chembl_36\\chembl_36_sqlite\\chembl_36.db。"],
  deploy: ["部署与接口", "本地运行、局域网部署、PyQt 桌面入口和接口文档。"],
};

let lastScientistReport = null;
const qwenStorageKey = "tcm_qwen_config";
const biancangModelId = "QLUNLP/BianCang-Qwen2.5-7B-Instruct";
const biancangBaseUrl = "http://127.0.0.1:8000/v1";
let qwenStatus = null;
let qwenModels = ["qwen-plus", "qwen-turbo", "qwen-max", "qwen-long", "qwq-plus", biancangModelId];

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[m]));
}

function formatCell(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return value ?? "";
}

function chips(id, items, cls = "") {
  const values = items || [];
  $(id).innerHTML = values.length
    ? values.map((item) => `<span class="chip ${cls}">${escapeHtml(item)}</span>`).join("")
    : "<span class='chip'>无结果</span>";
}

function table(id, rows, columns = null) {
  if (!rows || rows.length === 0) {
    $(id).innerHTML = "<p class='empty'>暂无数据</p>";
    return;
  }
  const cols = columns || Object.keys(rows[0]);
  const head = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const body = rows.map((row) => (
    `<tr>${cols.map((c) => `<td>${escapeHtml(formatCell(row[c]))}</td>`).join("")}</tr>`
  )).join("");
  $(id).innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function lines(id) {
  return $(id).value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
}

function clampPercent(value) {
  const number = Number(value) || 0;
  return Math.max(0, Math.min(100, number));
}

function displayPercent(value) {
  const number = Number(value) || 0;
  return number.toFixed(number % 1 === 0 ? 0 : 1);
}

function barRows(rows) {
  const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
  return rows.map((row) => {
    const value = Number(row.value) || 0;
    const width = value > 0 ? Math.max((value / max) * 100, 6) : 0;
    return `
      <div class="bar-row ${row.className || ""}">
        <div class="bar-meta"><span>${escapeHtml(row.label)}</span><b>${value}</b></div>
        <div class="bar-track"><span style="width:${clampPercent(width)}%"></span></div>
      </div>
    `;
  }).join("");
}

function statCards(items) {
  return `
    <div class="visual-summary">
      ${items.map((item) => `
        <article>
          <span>${escapeHtml(item.value)}</span>
          <label>${escapeHtml(item.label)}</label>
        </article>
      `).join("")}
    </div>
  `;
}

function resultChips(title, items, cls = "") {
  const values = (items || []).filter(Boolean);
  return `
    <section class="result-section">
      <div class="section-heading">
        <b>${escapeHtml(title)}</b>
        <span>${values.length} 项</span>
      </div>
      <div class="chips chart-chips">
        ${values.length
          ? values.map((item) => `<span class="chip ${cls}">${escapeHtml(item)}</span>`).join("")
          : "<span class='chip muted-chip'>暂无结果</span>"}
      </div>
    </section>
  `;
}

function renderIntersection(data) {
  const left = Number(data.left_count) || 0;
  const right = Number(data.right_count) || 0;
  const intersection = Number(data.intersection_count) || 0;
  const union = Math.max(left + right - intersection, 0);
  const overlapRate = union ? (intersection / union) * 100 : 0;
  const shared = data.intersection || [];

  $("intersectionResult").className = "chart-output";
  $("intersectionResult").innerHTML = `
    ${statCards([
      { label: "第一组靶点", value: left },
      { label: "第二组靶点", value: right },
      { label: "共同靶点", value: intersection },
      { label: "Jaccard重合率", value: `${displayPercent(overlapRate)}%` },
    ])}
    <div class="chart-layout">
      <div class="venn-card" aria-label="靶点交集示意图">
        <div class="venn-wrap">
          <div class="venn-circle venn-left"><b>${left}</b></div>
          <div class="venn-circle venn-right"><b>${right}</b></div>
          <div class="venn-overlap"><b>${intersection}</b><span>共同</span></div>
        </div>
        <div class="venn-legend">
          <span><i class="legend-dot left"></i>疾病侧 ${left}</span>
          <span><i class="legend-dot right"></i>方剂侧 ${right}</span>
        </div>
        <p>并集 ${union} 个靶点，交集占并集 ${displayPercent(overlapRate)}%。</p>
      </div>
      <div class="chart-bars">
        <h4>靶点规模对比</h4>
        ${barRows([
          { label: "第一组靶点", value: left, className: "primary" },
          { label: "第二组靶点", value: right, className: "secondary" },
          { label: "共同靶点", value: intersection, className: "accent" },
        ])}
      </div>
    </div>
    ${resultChips("共同靶点清单", shared, "target")}
  `;
}

function renderCompare(data) {
  const detected = Number(data.detected_count) || 0;
  const reference = Number(data.reference_count) || 0;
  const matched = Number(data.matched_count) || 0;
  const matchRate = Number(data.match_rate) || (detected ? (matched / detected) * 100 : 0);
  const unmatched = data.unmatched_detected || [];
  const referenceOnly = data.reference_only || [];

  $("compareResult").className = "chart-output";
  $("compareResult").innerHTML = `
    ${statCards([
      { label: "检测成分", value: detected },
      { label: "数据库成分", value: reference },
      { label: "命中成分", value: matched },
      { label: "匹配率", value: `${displayPercent(matchRate)}%` },
    ])}
    <div class="match-gauge">
      <div class="gauge-head">
        <span>检测数据匹配率</span>
        <b>${displayPercent(matchRate)}%</b>
      </div>
      <div class="progress-track"><span class="progress-fill" style="width:${clampPercent(matchRate)}%"></span></div>
      <p>已在数据库汇总中命中 ${matched} 个成分，仍有 ${unmatched.length} 个检测项需要人工复核。</p>
    </div>
    <div class="chart-bars">
      <h4>成分差异分布</h4>
      ${barRows([
        { label: "检测成分总数", value: detected, className: "primary" },
        { label: "数据库汇总总数", value: reference, className: "secondary" },
        { label: "已匹配成分", value: matched, className: "accent" },
        { label: "检测未命中", value: unmatched.length, className: "warning" },
        { label: "数据库独有", value: referenceOnly.length, className: "soft" },
      ])}
    </div>
    ${resultChips("已匹配成分", data.matched || [], "target")}
    ${resultChips("检测未命中", unmatched, "warn")}
    ${resultChips("数据库独有", referenceOnly, "soft")}
  `;
}

function show(view) {
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.id === view));
  document.querySelectorAll(".nav").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  $("viewTitle").textContent = titles[view][0];
  $("viewSubtitle").textContent = titles[view][1];
  window.location.hash = view;
}

function setBusy(el, busyText) {
  const old = el.textContent;
  el.disabled = true;
  el.textContent = busyText;
  return () => {
    el.disabled = false;
    el.textContent = old;
  };
}

async function refresh() {
  const health = await api("/api/health");
  qwenStatus = health.qwen || qwenStatus;
  $("statusBox").innerHTML = `<b>连接状态</b><span>后端正常 | 数据源 ${health.source_count} | ChEMBL ${health.chembl_available ? "可用" : "不可用"} | Qwen ${health.qwen?.configured ? "已配置" : "待配置"}</span>`;
  $("sourceCount").textContent = health.source_count;
  $("userCount").textContent = health.user_count;
  $("chemblState").textContent = health.chembl_available ? "可用" : "不可用";
  $("cacheState").textContent = health.cache_ready ? "已构建" : "未构建";
  renderQwenStatus();
  const sources = await api("/api/sources");
  table("sourcesTable", sources.items, ["key", "name", "exists", "size_mb", "fields"]);
}

function getQwenConfig() {
  return {
    api_key: $("qwenApiKey")?.value || "",
    base_url: $("qwenBaseUrl")?.value || "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: $("qwenModel")?.value || "qwen-plus",
  };
}

function isLocalBaseUrl(baseUrl = "") {
  try {
    const host = new URL(baseUrl).hostname;
    return ["127.0.0.1", "localhost", "::1"].includes(host);
  } catch {
    return false;
  }
}

function renderQwenModelOptions(selected = "") {
  const select = $("qwenModel");
  const current = selected || select.value || qwenStatus?.model || qwenModels[0];
  const models = [...new Set([...qwenModels, current].filter(Boolean))];
  select.innerHTML = models
    .map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`)
    .join("");
  select.value = models.includes(current) ? current : models[0];
}

function renderQwenStatus(text = "") {
  if (text) {
    $("qwenConfigState").textContent = text;
    return;
  }
  const cfg = getQwenConfig();
  if (qwenStatus?.configured && cfg.api_key) {
    $("qwenConfigState").textContent = `环境变量与临时 Key 均可用：${cfg.model}`;
  } else if (qwenStatus?.configured) {
    $("qwenConfigState").textContent = `环境变量已配置：${qwenStatus.model}`;
  } else if (isLocalBaseUrl(cfg.base_url)) {
    $("qwenConfigState").textContent = `本地模型服务：${cfg.model}`;
  } else if (cfg.api_key) {
    $("qwenConfigState").textContent = `已填写临时 Key：${cfg.model}`;
  } else {
    $("qwenConfigState").textContent = "未检测到环境变量，请输入临时 Key 或设置 DASHSCOPE_API_KEY";
  }
}

function useBianCangPreset() {
  $("qwenBaseUrl").value = qwenStatus?.biancang_base_url || biancangBaseUrl;
  $("qwenApiKey").value = "";
  renderQwenModelOptions(qwenStatus?.biancang_model || biancangModelId);
  $("qwenTestResult").className = "report-section";
  $("qwenTestResult").innerHTML = "<h4>已切换到本地 BianCang 模型</h4><p>请先启动本地 OpenAI 兼容服务，再点击“测试连接”。本地服务模式不需要填写真实 API Key。</p>";
  renderQwenStatus();
}

function loadQwenLocal() {
  try {
    const saved = JSON.parse(localStorage.getItem(qwenStorageKey) || "{}");
    if (saved.api_key) $("qwenApiKey").value = saved.api_key;
    if (saved.base_url) $("qwenBaseUrl").value = saved.base_url;
    if (saved.model) $("qwenModel").value = saved.model;
  } catch {
    localStorage.removeItem(qwenStorageKey);
  }
}

function saveQwenLocal() {
  localStorage.setItem(qwenStorageKey, JSON.stringify(getQwenConfig()));
  $("qwenTestResult").className = "report-section";
  $("qwenTestResult").innerHTML = "<h4>已保存</h4><p>配置已保存到当前浏览器 localStorage。不要在公共电脑上保存 API Key。</p>";
  renderQwenStatus("已保存到本浏览器");
}

function clearQwenLocal() {
  localStorage.removeItem(qwenStorageKey);
  $("qwenApiKey").value = "";
  $("qwenTestResult").className = "report-empty";
  $("qwenTestResult").textContent = "已清除本浏览器保存的 Qwen 配置。";
  renderQwenStatus();
}

async function testQwen(event) {
  const done = setBusy(event.target, "测试中...");
  try {
    const cfg = getQwenConfig();
    const data = await api("/api/qwen/test", {
      method: "POST",
      body: JSON.stringify({
        api_key: cfg.api_key || null,
        base_url: cfg.base_url || null,
        model: cfg.model || null,
      }),
    });
    $("qwenTestResult").className = data.ok ? "report-section" : "report-empty";
    $("qwenTestResult").innerHTML = data.ok
      ? `<h4>连接成功</h4><p>${escapeHtml(data.content)}</p><p>模型：${escapeHtml(data.model)}；Base URL：${escapeHtml(data.base_url)}</p>`
      : `连接失败：${escapeHtml(data.error || data.status_code || "未知错误")}`;
    renderQwenStatus(data.ok ? "连接测试成功" : "连接测试失败");
  } finally {
    done();
  }
}

async function initQwenConfig() {
  loadQwenLocal();
  try {
    const [status, models] = await Promise.all([
      api("/api/qwen/status"),
      api("/api/qwen/models"),
    ]);
    qwenStatus = status;
    qwenModels = models.items?.length ? models.items : qwenModels;
    if (!$("qwenBaseUrl").value && models.base_url) $("qwenBaseUrl").value = models.base_url;
    renderQwenModelOptions(getQwenConfig().model || models.default || status.model);
    renderQwenStatus();
  } catch (err) {
    renderQwenModelOptions(getQwenConfig().model);
    renderQwenStatus(`Qwen配置读取失败：${err.message}`);
  }
}

async function searchDisease() {
  const data = await api(`/api/search/disease?q=${encodeURIComponent($("diseaseInput").value)}&limit=120`);
  chips("diseaseHerbs", data.herbs);
  chips("diseaseTargets", data.targets, "target");
  table("diseaseLinks", data.links, ["疾病", "中药", "靶点基因"]);
  $("diseaseHerbCount").textContent = `${data.counts?.herbs ?? data.herbs.length} 项`;
  $("diseaseTargetCount").textContent = `${data.counts?.targets ?? data.targets.length} 项`;
}

async function searchHerb() {
  const data = await api(`/api/search/herb?q=${encodeURIComponent($("herbInput").value)}&limit=160`);
  chips("herbComponents", data.components);
  chips("herbTargets", data.targets, "target");
  table("herbLinks", data.links, ["source", "herb", "component", "targets"]);
  $("herbComponentCount").textContent = `${data.counts?.components ?? data.components.length} 项`;
  $("herbTargetCount").textContent = `${data.counts?.targets ?? data.targets.length} 项`;
}

async function searchComponent() {
  const data = await api(`/api/search/component?q=${encodeURIComponent($("componentInput").value)}&limit=160`);
  chips("componentTargets", data.targets, "target");
  table("componentLinks", data.links, ["source", "herb", "component", "targets"]);
  $("componentTargetCount").textContent = `${data.counts?.targets ?? data.targets.length} 项`;
}

async function intersect() {
  const data = await api("/api/targets/intersection", {
    method: "POST",
    body: JSON.stringify({ left: lines("leftTargets"), right: lines("rightTargets") }),
  });
  renderIntersection(data);
}

async function compare() {
  const data = await api("/api/components/compare", {
    method: "POST",
    body: JSON.stringify({ detected: lines("detectedComponents"), reference: lines("referenceComponents") }),
  });
  renderCompare(data);
}

async function searchChembl() {
  const data = await api(`/api/chembl/molecules?q=${encodeURIComponent($("chemblInput").value)}&limit=30`);
  table("chemblMolecules", data.items, ["chembl_id", "pref_name", "molecule_type", "max_phase", "natural_product", "canonical_smiles"]);
  $("chemblActivities").innerHTML = "<p class='empty'>默认展示第一条分子的活性数据。</p>";
  if (data.items && data.items[0]) {
    const activities = await api(`/api/chembl/activities?chembl_id=${encodeURIComponent(data.items[0].chembl_id)}&limit=30`);
    table("chemblActivities", activities.items, ["target_chembl_id", "target_name", "organism", "standard_type", "standard_relation", "standard_value", "standard_units", "pchembl_value"]);
  }
}

function list(items) {
  return `<ul>${(items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderScientistReport(data) {
  const results = data.results || {};
  const qwenOk = data.qwen_result?.ok;
  $("scientistMeta").textContent = `共同靶点 ${results.intersection_count ?? 0} 个`;
  $("scientistReport").className = "report";
  $("scientistReport").innerHTML = `
    <section class="report-section">
      <h4>Qwen 增强状态</h4>
      <p>${qwenOk ? "已启用 Qwen 增强生成。" : escapeHtml(data.qwen_result?.error || "当前为本地证据整合报告。")}</p>
    </section>
    ${data.qwen_enhanced_text ? `
    <section class="report-section">
      <h4>Qwen Enhanced Scientific Plan</h4>
      <p>${escapeHtml(data.qwen_enhanced_text).replace(/\n/g, "<br>")}</p>
    </section>` : ""}
    <section class="report-section">
      <h4>Paper Title</h4>
      <p>${escapeHtml(data.paper_title)}</p>
    </section>
    <section class="report-section">
      <h4>Problem Statement</h4>
      <p>${escapeHtml(data.problem_statement)}</p>
    </section>
    <section class="report-section">
      <h4>Paper Abstract</h4>
      <p>${escapeHtml(data.paper_abstract)}</p>
    </section>
    <section class="report-section">
      <h4>Rationale</h4>
      ${list(data.rationale)}
    </section>
    <section class="report-section">
      <h4>Technical Details</h4>
      ${list(data.technical_details)}
    </section>
    <section class="report-section">
      <h4>Methods</h4>
      ${list(data.methods)}
    </section>
    <section class="report-section">
      <h4>Experiments</h4>
      <p><b>Baselines：</b>${escapeHtml((data.experiments?.baselines || []).join("；"))}</p>
      <p><b>Metrics：</b>${escapeHtml((data.experiments?.metrics || []).join("；"))}</p>
      <p><b>Validation：</b>${escapeHtml((data.experiments?.validation || []).join("；"))}</p>
    </section>
    <section class="report-section">
      <h4>Results</h4>
      <p>疾病靶点：${results.disease_target_count ?? 0} 个；方剂靶点：${results.formula_target_count ?? 0} 个；共同靶点：${results.intersection_count ?? 0} 个。</p>
      <p><b>优先靶点：</b>${escapeHtml((results.top_intersection_targets || []).slice(0, 16).join(", ") || "暂无")}</p>
      <p><b>代表性成分：</b>${escapeHtml((results.representative_components || []).slice(0, 16).join(", ") || "暂无")}</p>
    </section>
    <section class="report-section">
      <h4>References</h4>
      ${list(data.references)}
    </section>
  `;

  const summaries = data.evidence?.herb_summaries || [];
  $("evidenceSummary").innerHTML = summaries.length
    ? summaries.map((item) => `
      <article>
        <b>${escapeHtml(item.herb)}</b>
        <span>成分 ${item.component_count} 个，靶点 ${item.target_count} 个</span>
      </article>
    `).join("")
    : "<p class='empty'>暂无证据摘要</p>";
}

async function generateScientist(event) {
  const done = setBusy(event.target, "生成中...");
  try {
    const data = await api("/api/scientist/hypothesis", {
      method: "POST",
      body: JSON.stringify({
        question: $("scienceQuestion").value,
        disease: $("scienceDisease").value,
        formula: $("scienceFormula").value,
        focus: $("scienceFocus").value,
        use_qwen: $("scienceUseQwen").checked,
        qwen_api_key: getQwenConfig().api_key || null,
        qwen_base_url: getQwenConfig().base_url || null,
        qwen_model: getQwenConfig().model || null,
      }),
    });
    lastScientistReport = data;
    renderScientistReport(data);
  } finally {
    done();
  }
}

function toMarkdown(data) {
  if (!data) return "";
  const results = data.results || {};
  return [
    `# ${data.paper_title}`,
    "",
    "## Problem Statement",
    data.problem_statement,
    "",
    "## Paper Abstract",
    data.paper_abstract,
    "",
    "## Rationale",
    ...(data.rationale || []).map((item) => `- ${item}`),
    "",
    "## Technical Details",
    ...(data.technical_details || []).map((item) => `- ${item}`),
    "",
    "## Methods",
    ...(data.methods || []).map((item) => `- ${item}`),
    "",
    "## Experiments",
    `- Baselines: ${(data.experiments?.baselines || []).join("；")}`,
    `- Metrics: ${(data.experiments?.metrics || []).join("；")}`,
    `- Validation: ${(data.experiments?.validation || []).join("；")}`,
    "",
    "## Results",
    `- Disease targets: ${results.disease_target_count ?? 0}`,
    `- Formula targets: ${results.formula_target_count ?? 0}`,
    `- Intersection targets: ${results.intersection_count ?? 0}`,
    `- Top targets: ${(results.top_intersection_targets || []).join(", ")}`,
    "",
    "## References",
    ...(data.references || []).map((item) => `- ${item}`),
  ].join("\n");
}

function downloadScientist() {
  if (!lastScientistReport) {
    alert("请先生成研究计划。");
    return;
  }
  const blob = new Blob([toMarkdown(lastScientistReport)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "scientific_hypothesis_plan.md";
  a.click();
  URL.revokeObjectURL(url);
}

const actions = {
  searchDisease,
  searchHerb,
  searchComponent,
  intersect,
  compare,
  searchChembl,
  generateScientist,
  downloadScientist,
  testQwen,
  saveQwenLocal,
  clearQwenLocal,
  useBianCangPreset,
};

document.querySelectorAll(".nav").forEach((btn) => {
  btn.addEventListener("click", () => show(btn.dataset.view));
});

document.querySelectorAll("[data-jump]").forEach((btn) => {
  btn.addEventListener("click", () => show(btn.dataset.jump));
});

document.querySelectorAll("[data-action]").forEach((btn) => {
  btn.addEventListener("click", (event) => {
    actions[btn.dataset.action](event).catch((err) => alert(err.message));
  });
});

$("refreshBtn").addEventListener("click", () => refresh().catch((err) => alert(err.message)));

const initialView = window.location.hash.replace("#", "");
if (titles[initialView]) show(initialView);

initQwenConfig()
  .then(() => refresh())
  .catch((err) => {
    $("statusBox").innerHTML = `<b>连接状态</b><span>后端连接失败：${escapeHtml(err.message)}</span>`;
  });
