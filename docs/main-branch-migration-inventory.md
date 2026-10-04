# main 分支代码迁移盘点

盘点基线：`origin/main`，提交 `078d374`（2026-10-02）。当前目标分支：`codex/django-foundation-hardening`。本文把 main 当作页面、业务算法和数据字段的参考来源；不合并整条分支，逐个模块移植到 Django + React/Vite 后通过测试再启用。

2026-10-03 范围确认：当前阶段先迁移 `main` 中确有源码的页面与业务行为，不再新造计划外业务模块，也不先写临时替代品再推倒重做。为迁移必需的 Django API、路由、权限、统一错误格式和测试可以补齐。若旧功能依赖未随仓库提供的数据文件或服务，则保留页面/清单位置并明确标注“待迁移/待数据”，等依赖可核验后再补。计划文档里 `main` 没有的扩展能力放在后续阶段单独实施。

## 迁移规则

2026-10-04 复刻收尾：已恢复 main 公共侧栏/顶栏、原五项移动导航、检索标签布局、文本分析正文及首页三张卷轴 PNG，并修正网络候选统计和直接关联候选的中药字段。实际 Django + 构建静态前端已通过合成数据 HTTP 联调；浏览器实际渲染、真实研究样例和旧数据导入仍未验收。详见 [UI 与结果复刻核验](main-ui-and-result-parity.md)。

- React 组件和 CSS 可以复用交互与视觉结构，但 `next/navigation`、Next.js Server Actions、Prisma 查询必须改为 React Router、Django API 和当前设计系统。
- 领域算法优先复用并迁到 Python 业务服务，需建立输入/输出样例并与 main 结果对照后才能替换旧路径。
- 旧版数据使用 Prisma/SQLite，Django 使用 PostgreSQL 和新表结构。只迁字段含义，不直接复制 SQLite 表或未经盘点的数据。
- 登录使用 Django 服务端 session 和 CSRF。旧项目的 Cookie/JWT 解析、内置默认管理员密码和角色逻辑不作为新系统鉴权实现。
- 旧 API 若依赖 Windows 固定路径、`data_cache.db`、Excel 本地文件、公开模型地址或 SQLite，应先抽出领域逻辑和数据契约，再改造成配置化服务。

### 认证与账号迁移

`origin/main` 的旧 Cookie/JWT 判定方式不作为新平台的认证实现；新系统由 Django 服务端 session 识别用户，并以服务端 `request.user` 绑定研究者提交的数据。新注册流程属于 Django 安全基础设施补齐，没有可直接复用的 main 业务代码：账号初始停用、无 staff/superuser 权限，先以 24 小时有时限的签名邮件链接确认邮箱，再由管理员审核启用。验证确认由单独 CSRF 保护的 POST 完成，重发链接不透露邮箱是否存在；验证成功后才向配置的管理员邮箱发通知。后台改研究者邮箱会清除验证时间并停用账号。迁移 `0017_researcherprofile` 为历史非管理员账号创建邮箱状态；既有 active 用户按迁移时刻标记为历史已验证，以免升级后失去登录能力。SMTP、退信和生产收件流程尚需部署环境验收。

## 页面与业务迁移映射

| main 分支源码 | main 中的用途 | 当前 Django + React/Vite 目标 | 状态 |
|---|---|---|---|
| `src/app/api/research/route.ts#pathway`、`ResearchWorkbench.tsx#PathwaySearchResult` | 本地 Reactome 人类目录名称/编号检索、注释数量和导出 | `/research` 的通路目录组件 + `/api/v1/catalog/pathways/reactome/` | 已迁移启用、活动且有来源版本的 R-HSA 人类目录，名称排序、最多 100 项，保留实际版本/校验值和去重基因/蛋白注释来源；空目录、无匹配和截断有提示。CSV/JSON 导出包含同一结果及来源，旧全局富集表未迁入，显示“未迁入”，不访问研究者私有任务。6 项 API 测试及合成数据页面检索/分页/错误提示通过；浏览器 Blob 文件落盘仍需常规浏览器确认 |
| `src/components/AppShell.tsx`、`AppNavigation.tsx`、`PageHeader.tsx`、`src/app/product.css` | 主导航、页面框架和产品视觉样式 | `web/src` 中复用样式/交互，路由改为 React Router | 首页、医案和数据集已接入；共享工作台导航已统一，保留原有标签和视觉样式 |
| `src/app/dashboard/page.tsx`、`src/app/api/dashboard/route.ts` | 展示登录用户的数据集、医案、任务数量，知识库规模和最近五项任务 | React `/dashboard` + 登录保护的 `/api/v1/research/dashboard/` | 已迁移；研究者只看本人记录，超级管理员可看全部，知识实体按启用来源统计；登录后默认进入总览 |
| `src/app/api-integration/page.tsx`、`ApiIntegrationConsole.tsx`、`src/app/api/integrations/{status,test}/route.ts` | 管理员查看服务状态并测试疾病/中药/成分/ChEMBL/靶点交集/成分比对/Qwen/AI Scientist 调用链 | React `/admin/integrations` + 超级管理员 Django API `/api/v1/admin/integrations/` | 已迁入原监测页及主要测试项；状态映射为 Django/数据库、数据源目录和本机模型配置。疾病、中药、成分、交集与成分比对检查复用当前 Django 服务，交集为只读不建任务；ChEMBL 和本机模型需逐次同意并限流。旧 AI Scientist 依赖仓库缺失的 Excel/SQLite 数据，页面明确标待迁移，不伪造替代结果。6 项权限、同意门槛、只读行为和缺失依赖测试通过 |
| `src/app/cases/page.tsx`、`src/components/CaseForm.tsx`、`src/app/api/cases/*` | 医案新增、列表、删除 | `/cases` + `/api/v1/research/cases/`，归属由 Django session 决定 | 创建/查看/删除 UI 已接入；API 支持更新和 `q` 查询（标题、脱敏正文、诊断），搜索仍先按所有者过滤。创建、变更、删除和平台管理员审核会追加隐私友好审计记录；本人只查看自己的记录，超级管理员可查看全部并审核。日志保存操作者、时间、字段名和内容哈希，不重复保存医案正文。已补入安全版第一步：本机/内网模型结构化、逐字引文校验、规范实体精确匹配、研究者逐条确认/驳回、隐私友好审计及有来源版本的下游证据链；新增受限 RAG，从医案提及中检索启用来源版本实体和一跳关系，知识引用必须命中本次检索记录白名单，不同来源分别保留并展示。真实模型、项目样例、更广文献语料/语义检索及下游药理/组学任务编排仍待完成 |
| `src/app/datasets/page.tsx`、`DatasetUploader.tsx`、`DeleteButton.tsx`、`src/app/api/datasets/*` | 上传 CSV/Excel、查看数据集、删除 | `/datasets` + `/api/v1/research/datasets/`，文件私有保存、带校验值和权限下载 | 私有文件 CRUD 已接入；`q` 查询支持名称/原始文件名且保持所有者隔离；数据集被分析任务引用后禁止替换或删除 |
| `src/lib/upload.ts` | CSV、XLS、XLSX 表格解析 | Python 解析器，限制大小/行/列/单元格、保留原始文件并生成逐行 QC | CSV/TSV/XLS/XLSX 已支持第一版解析与行数限制；已保存 main 前 5,000 行的有界预览（创建响应 25 行、详情 100 行）；main 数据集页面本身没有独立预览表格；真实样例逐项结果对照仍待完成 |
| `src/app/proteomics/page.tsx`、`ProteomicsWorkbench.tsx`、`src/lib/proteomics.ts`、`src/lib/reactome.ts`、`src/app/api/proteomics/*` | 列映射、差异蛋白阈值、MyGene 标识规范化、Reactome 富集、通路网络和候选交集 | React `/proteomics` + Django API + Celery；本地知识库映射、用户显式同意后调用 MyGene/Reactome/STRING/g:Profiler、任务结果与来源版本持久化 | 第一版本地链路已接入：自动常见列名/手动列名、阈值/QC、显式标记未验证符号、本地实体及通路证据、候选交集、任务行记录和 CSV/XLSX/JSON 导出；MyGene/Reactome 外部调用默认关闭，最多处理 500 个通过筛选的人类标识，歧义不自动采用；GO/KEGG 为单独同意项（`main` 没有对应实现，本分支按计划新接 [g:Profiler 官方 API](https://biit.cs.ut.ee/gprofiler/page/apis)），最多提交 500 个显著查询符号和 25,000 个可识别输入符号作自定义背景，FDR 校正并记录服务及完整数据版本；STRING 物理 PPI 是另一独立同意项，最多提交 200 个标识，置信度默认 700/1000，结果单独展示；当前分支对返回的无向物理互作图计算唯一邻居 degree 与归一化无权 Brandes betweenness（main 原实现只计算本地靶点—通路图 degree）；默认自动发现 STRING 版本并使用版本专属 API 地址，`STRING_DB_VERSION` 可显式固定版本。新增 g:Profiler 官方 API 契约测试，模拟数据全套测试通过；2026-10-03 已向官方富集 POST 发送 5 个公开合成基因符号及 25 个自定义背景标识：服务返回版本 e114_eg62_p19_27110d83 和各来源版本，响应有效但没有 FDR≤0.05 条目；这只验证连通性、请求字段与响应解析，不构成生物学结果或 main 黄金样例对照。main 中没有提交可核对的 proteomics 样例数据。原始定量矩阵首版已接入显式设计的非配对 Welch 与逐对指定的配对 t 检验、BH-FDR 和用户指定样本设计；算法版本 `proteomics-py-1.6` 新增研究者逐样本指定分类因素、指定主要对比的加性线性模型 t 检验，记录样本/水平/参考组/自由度，不拟合交互项并拒绝完全混杂设计；本地版本化稳定 ID 与用户同意后唯一 MyGene Entrez ID 已贯通逐行结果和 CSV/XLSX/PDF；R 火山图已增加持久化统计数据的有界绘图任务和页面入口，但 Docker/R 容器尚未实跑；真实实验样例验收、非人类/全量 ID 覆盖、R 交互图和 R 容器实跑仍待完成 |
| `src/app/analysis/page.tsx`、`AnalysisWorkbench.tsx`、`src/lib/analysis.ts`、`src/app/api/analysis/tasks/*` | 医案/文本分析和任务结果；main 中的四组证候关键词规则、稳定排序和知识链展示 | Django `/api/v1/research/text-analysis/` + React `/analysis`；结果、输入、算法版本和来源版本持久化 | main 的四组关键词规则已按原顺序迁入 Python 服务，任务保存查询、命中分数、规则来源、证据关系和来源校验快照，支持最近任务、CSV/PDF 导出及权限隔离；无命中会明确返回无规则命中，不复制旧版“回退第一条证候”的行为，候选也不会自动变成确诊或医案候选。绑定医案时保留医案所有者并追加审计记录。旧版本机模型/更广 RAG 属于另一条依赖数据与模型的链路，仍按原状态待后续验收，不与这套可独立复刻的关键词规则混在一起 |
| `src/app/research/page.tsx`、`ResearchWorkbench.tsx`、`src/app/api/research/route.ts`、`src/lib/disease-query.ts#exactAliases` | 研究问题、证候/方剂/药物等证据链 | Django research/knowledge service 与 React 研究工作台 | 已迁移本地只读检索切片：React `/research` 可按实体类型/名称查目录，查看一个实体双向最多 200 条来源版本关系并导出 JSON；API 仅读启用实体与活动关系。ChEMBL 查询已迁入一条官方 REST 纵向切片：登录并逐次勾选同意后，查询词才发送至 ChEMBL 官方 API，显示限量化合物结果、ChEMBL 版本/日期与按化合物编号查询的标准活性、靶点和 assay；活性筛选复现 main 的“标准测量值或 pChEMBL 非空”条件及 pChEMBL 降序空值置后，并沿用 main 的天然产物标记；不传医案/上传文件，不写入用户数据表。沿用 main 的字段含义，但不复制其开发机 SQLite 路径。已从 main 迁入 37 组中英文/拉丁名称对应，并将其用于 ChEMBL 检索扩展；同时迁入 main 的检测成分—用户参考列表名称对照算法，输出精确匹配与单独标注的同家族候选。成分比对页已复用 main 的韦恩图配色/几何、视口分页、规范化名称清单及交集/完整比对/规范化清单 CSV；保留别名表出处，导出全部分页记录并防护 CSV 公式；“仅参考”行按来源显示在参考列，同家族候选独立分页。该对照只是用户所给名称列表的标准化，不读取旧参考库、不校验检测数据真实性。已迁入 main 的 51 组中文疾病精确别名，Django 将其用于启用本地 disease 实体目录查询，展示展开词、实际匹配词、目录来源版本和别名表来源提交；不把泛化 token 规则搬入，也不把别名当成实体证据。main 的批量中药/成分关系查询已迁为登录后本地目录检索：每次最多 12 项，可按中药查成分—靶点或按成分反查来源中药/靶点；精确同名实体并列保留，关系逐条显示来源版本和记录号，不读取旧电脑文件；外部接口许可与引用要求仍需核对 |
| `src/app/api/network-pharmacology/route.ts`、`pathway-enrichment/route.ts`、`src/lib/reactome.ts`、`NetworkPharmacologyWorkbench.tsx` | 靶点交集、Reactome 富集和网络药理视图 | Django connector/service；任务固定数据源版本，页面显示证据来源 | 本地中药—成分—靶点 × 疾病—靶点交集 API/页面已接入；只按目录精确名称匹配，保存任务归属、来源版本和关系证据。用户显式同意后可异步请求 Reactome 富集和 STRING 物理互作（各有输入上限）。UniProt 本地目录作为新增迁移 connector（`main` 无同步源码）：官方 reviewed 人类目录分页同步、人工预览应用、版本化外部 identifier 已完成，20,431 条在临时 SQLite 验证幂等。PubChem PUG REST 属性 connector 也已实现，但只支持管理员人工映射 CID→本地 compound stableId；main seed 中 6 个 CID 的真实 API 响应通过校验，1 个 CID 的预览/应用/重复预览幂等已在一次性 SQLite 验证，数据未写入项目数据库。STRING ID 人类映射连接器为新增实现（`main` 仅含 STRING PPI 查询，没有目录同步源码）：只对已有、明确标注为人类或由 UniProt reviewed 人类来源标识确认的本地实体调用版本化 `get_string_ids`，管理员预览后应用，不自动创建/合并实体或改绑冲突标识；STRING v12.5 的 TP53 API 联通实测与模拟映射/冲突/幂等/权限测试通过，真实本地目录/开发 PostgreSQL 同步未验收。网络药理结果页现有基于 main 分层图数据的 React/SVG 交互网络，已补齐靶点交集、成分和通路统计图，以及候选靶点 CSV、来源证据 CSV 与完整结果 JSON 下载；保留任务查询、来源版本和记录号，明确每个靶点最多 30 条证据和最多 1,000 个候选靶点的截断范围；尚无 R 交互网络工件。GO/KEGG 已接入蛋白组学页面，尚缺 main 黄金样例核对、外部 Reactome 富集/STRING PPI 专用可视化、真实项目 CID 映射验收和真实 PostgreSQL 来源同步验收 |
| `src/app/admin/page.tsx`、`DatabaseSyncConsole.tsx`、`ReactomeCatalogSync.tsx`、`src/lib/database-sync.ts`、`backend/cache_builder.py` | 管理员用户/资产总览、数据源管理、测试和同步；旧缓存由中药—成分—靶点、疾病—靶点、疾病—中药—靶点三表构成 | React `/admin` 平台总览、`/admin/sources` 数据源控制台、`/django-admin/` 配置后台；受超级管理员权限保护的 Django API | main 管理页的只读用户列表、角色/账号状态/资产数，以及最近 10 项数据集和任务已迁入 `/admin`；注册时间和最近登录使用 Django 实际字段。Reactome 后台预览/人工应用已接入，真实目录 2,883 条已在临时 SQLite 上验证；旧 SQLite 连接器现可配置 main `cache_builder.py` 生成的三张表，预览全部实体/关系，按 SHA-256 与配置版本人工确认、批量幂等导入并软停用旧关系；UniProt 人类 reviewed 蛋白目录和 PubChem 属性读取也有版本化预览/人工应用。PubChem 必须先由管理员配置 CID→本地 compound stableId，不按名称猜测；合成三表端到端通过，6 个 main 示例 CID 响应通过校验，1 个 CID 的临时 SQLite 应用与幂等检查通过，未写入项目数据库；STRING 本地人类标识交叉映射已提供版本化预览/人工应用，STRING v12.5 单条官方 API 联通测试和模拟来源同步测试通过，尚未对本地全量实体/PostgreSQL 执行同步；主机目录仅通过 `SQLITE_SOURCE_ROOT` 挂载且只读，不接受任意绝对路径。管理员现可删除未使用的数据源登记；已有来源版本或任何同步历史时返回 409 保留溯源，原文件和知识记录不删除。原 SQLite 文件仍不在仓库，真实字段语义和规模未核实 |
| `src/app/assistant/page.tsx`、`AssistantWorkspace.tsx`、`src/app/api/assistant/route.ts`、`backend/qwen_service.py` | 科研助手和 Qwen/BianCang 接口 | `/assistant` + `/api/v1/research/assistant/` + Celery；调用已配置的本机/内网 OpenAI 兼容模型 | 已迁移受控首版：研究者先从启用来源版本目录中选择最多 8 个实体，后端冻结实体/一跳关系/证据来源版本快照并创建归属当前用户的异步任务；默认只返回目录证据，只有每次显式同意才向平台配置的本机/内网模型发送本次问题及所选证据。公网模型地址、HTTP 代理和重定向不允许；模型输出为 JSON，引用仅保留本次白名单 refId，未引用结果会显示警示。页面展示模型名/版本、来源记录和任务状态。旧助手中硬编码方剂组成、疾病/方剂自动猜测、泛化规则回答和无证据模型 fallback 不复制。真实模型部署联调、黄金样例及更广 RAG/语义检索仍待完成 |
| `src/app/api/analysis/results/*`、`src/lib/exporters.ts`、`Charts.tsx`、`NetworkGraph.tsx` | 结果、CSV/PDF 导出和图形展示 | Django 授权结果 API；React 交互图表；R 工件后续集成 | 网络药理汇总柱图和蛋白组学 GO/KEGG 富集气泡图接入同一 Plumber 任务链；后者只传最多 100 条有效富集名称、来源类别、GeneRatio、FDR 和命中数，并在图中显示 g:Profiler 版本。worker 校验返回 SHA-256/文件类型，将 SVG/PDF/PNG/HTML 存入私有媒体并通过 Django 所有者权限下载；网页显示原始表格，HTML 图表另附对应数据表。蛋白组学授权导出已增加中文 PDF 汇总报告，含参数、质量提示、来源版本和最多 500 条重点结果；完整逐行数据仍由 CSV/XLSX 提供。文本规则分析已增加保留 `level,value` 结构及来源版本/关系记录的 CSV 和中文 PDF；CSV 含公式防护，PDF 经长中文合成报告渲染核对，静态缺字分隔符已修复。R/Docker 镜像仍未实跑，R 交互图、main 样例对照和下载量/超时生产压测仍缺 |

main 的 `src/app/visualization/page.tsx` 实际复用 `NetworkPharmacologyWorkbench`，该业务入口由当前 `/network-pharmacology` 覆盖，不另造新的可视化业务模块。

### ChEMBL 官方查询迁移（2026-10-03）

旧 `origin/main` 的 `backend/chembl_service.py` 通过本机 ChEMBL SQLite 执行化合物与 assay 活性连接查询；所需 `chembl_36.db` 不在仓库，不能直接运行或迁移旧数据。本分支新增 Django 认证 API，使用 ChEMBL 官方 Data Web Services 的 `molecule/search` 与 `activity` 端点。每个展开检索词最多取 10 个分子，总列表最多 40 个；活性表最多 50 行，并复现 main 的“standard_value 或 pChEMBL 非空”条件和 pChEMBL 降序、缺失项后置。请求固定官方 HTTPS 主机、拒绝重定向、限制响应体、20 秒超时，并按用户每小时 10 次限流。API 强制 `consent: true`，前端默认未勾选；只有查询词及选中的 ChEMBL 编号会送往官方服务，不发送医案正文、上传文件或账号标识。页面展示数据版本、发布时间、获取时间、记录链接及活性单位/assay/靶点字段，并提示实验活性不代表临床疗效。2026-10-03 官方 `status.json` 返回 ChEMBL 37（2026-05-01）；英文 `quercetin` 与中文“槲皮素”检索以及 CHEMBL50 活性查询完成只读在线核对，未将其作为药理学黄金样例。

别名表 `python_app/apps/core/data/component_aliases.json` 从 `origin/main@078d374` 的 `COMPONENT_ALIASES` 提取 37 组名称。名称比较 API 复用 main `compareComponentsMultilingual` 的标准化、去重、精确匹配和家族候选规则；由研究者输入检测列表与参考列表，家族相似不计入精确命中率，不读取未随仓库提供的参考数据库，也不验证检测值。别名展开每次最多 8 个外部检索词，单个词取 10 个分子，最多并行 4 个官方查询；失败子查询会随成功结果明确展示。ChEMBL 搜索/活性复用按用户每小时 10 次限流。自动测试使用模拟响应，不把在线结果当作药理学黄金样例；用户是否要将外部活性保存进本地目录仍需后续设计/审批。官方 API 文档：[ChEMBL Data Web Services](https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services)。

## main 中的重要数据对象

`prisma/schema.prisma`（SQLite）主要包含：

- 账号与归属：`User`、`Dataset`、`MedicalCase`、`AnalysisTask`。
- 文件/表格：`DatasetRow`、`ProteomicsDataset`、`ProteomicsRow`、`ProteomicsAnalysis`。
- 研究知识：`Syndrome`、`Formula`、`Herb`、`Compound`、`Target`、`Gene`、`Pathway`。
- 结果与来源：`AnalysisResult`、`PathwayEnrichmentRun`、`PathwayEnrichmentItem`、`DatabaseSource`、`DatabaseSyncRun`。

当前 Django 已有 `ResearchDataset`、`MedicalCase`、`MedicalCaseAuditEvent`、`AnalysisTask`、`VisualizationArtifact`、`KnowledgeEntity`、`EvidenceRelation`、`DataSource`、`SourceRelease` 和 `SyncRun`。迁移时要优先做字段映射：例如 main 的多个知识实体表映射到 Django 的实体类型/规范 ID；`DatasetRow` 仅按 main 已有的前 5,000 行策略入库，完整原文件仍在私有存储中；蛋白组学行级结果、任务结果及图表工件继续使用各自的受控模型。

### 首版字段映射

| main SQLite/Prisma 对象 | Django/PostgreSQL 映射方向 | 需要保留或转换的内容 |
|---|---|---|
| `User` | Django `AUTH_USER_MODEL` | main 的字符串 CUID 与 Django 主键不同；导入时需做稳定 ID/email 对照，密码 hash 格式须验证，角色不得直接信任 |
| `Dataset` | `ResearchDataset` | 名称、说明、上传人、文件名；记录私有 storage key、SHA-256、字节数、解析行数和字段名 |
| `DatasetRow` | `ResearchDatasetRow` | 上传时解析 CSV/TSV/XLS/XLSX；数据库保存前 5,000 行，创建响应最多返回 25 行，详情最多返回 100 行 |
| `MedicalCase` | `MedicalCase` | `symptoms` → `deidentified_text`；`patientInfo/tonguePulse/diagnosis` → `structured_data`；`source` → `source_reference`；记录用户和时间 |
| `AnalysisTask` / `AnalysisResult` | `AnalysisTask` + 待设计结果/工件模型 | 输入医案、参数、状态、证据、网络、算法/来源版本分别建模；不能把历史 `COMPLETED` 假设成新任务状态 |
| `ProteomicsDataset` / `ProteomicsRow` / `ProteomicsAnalysis` | `ResearchDataset` + `AnalysisTask` + `ProteomicsRowResult` | 原始文件 SHA-256、列映射、阈值、算法版本、逐行原始标识/规范标识/映射状态/排除原因和来源版本均已入账；差异统计矩阵、外部富集结果、PPI 和可视化工件模型仍待扩展 |
| `Syndrome` / `Formula` / `Herb` / `Compound` / `Target` / `Gene` / `Pathway` | `KnowledgeEntity` + `EvidenceRelation`，必要时扩充类型字段 | 保留外部 ID、规范 ID、物种、关系类型、证据分值、来源版本；导入前做唯一键与重复规则 |
| `DatabaseSource` / `DatabaseSyncRun` | `DataSource` / `SourceRelease` / `SyncRun` | 来源配置不含明文密钥；保留游标、运行状态、版本、计数、摘要和失败阶段 |

以上只是代码层映射草案，不构成历史数据导入授权或生产迁移步骤。需要确认每个数据文件的许可、敏感性、编码、记录量和实际主键后，才能编写数据迁移脚本。

## main 的 API / Python 服务目录

- Next.js API Routes 按 auth、datasets、cases、analysis、assistant、network pharmacology、proteomics、admin/sources 分组。新系统分别归到 `/api/v1/auth/`、`research/`、`catalog/`、`analysis/`、`admin/`，不会逐字照搬 Next API 路径。
- FastAPI `backend/main.py` 暴露健康检查、来源列表、疾病/中药/成分检索、靶点交集、成分比较、ChEMBL 和本地模型接口。
- `backend/data_service.py` 依赖 pandas、旧 Excel/SQLite 来源和 `data_cache.db`；`chembl_service.py` 提供 ChEMBL 查询；`qwen_service.py` 提供 OpenAI 兼容聊天适配。
- main 里的 `src/lib/proteomics.ts`、`analysis.ts`、`database-sync.ts`、`reactome.ts` 是最值得优先对照的可复用业务算法；需要补 Python 实现和跨语言输出对照测试，不能在 TS 页面里继续藏业务逻辑。

### 旧代码引用的数据文件与当前可用性

已检查 `origin/main`（`078d374`）内受 Git 跟踪的文件：目前没有找到可直接导入的 `.db`、`.sqlite`、`.csv`、`.tsv`、`.xls`、`.xlsx` 或压缩数据集文件。旧 `backend/config.py` 与 `backend/data_service.py` 依赖开发者机器上的项目目录、Excel 文件和 SQLite 缓存；其中配置明确提到：

- `database/` 目录下的数据集（代码按不同用途查找药物、疾病、成分和靶点工作簿）。
- `系统验证所需数据/` 目录。
- `app.db`、`data_cache.db`。
- `D:\chembl\chembl_36\chembl_36_sqlite\chembl_36.db`（硬编码 Windows 路径，可由 `TCM_CHEMBL_DB` 覆盖）。
- 后端还引用 `Batman全部数据.xlsx`、`Herb数据库全部.xlsx`、`HIT数据库全部.xlsx`、`TCMIP全部数据.xlsx`、`tcmsp全部数据.xlsx`、`疾病_中药.xlsx`、`combined_results.xlsx` 等工作簿名称；这些文件当前不在 Git 仓库中。

因此目前能借鉴的是代码中的字段、查询方式和算法，不能据此认定原始研究数据已经随仓库交付，也不能直接完成历史数据导入。数据持有人还需提供实际文件/可访问位置、许可或使用依据、敏感字段说明和版本信息；导入前另做格式与主键盘点、脱敏检查、记录数核对和备份/回滚演练。没有这些材料时，新系统只可测试空库和合成样例。

## 尚待盘点冻结的事项

- 逐个旧数据文件登记实际路径、格式、记录数、来源、许可和是否有身份/健康敏感字段。
- 建立 Prisma → Django 字段映射、主键映射、导入/去重规则和可回退备份步骤。
- 为 proteomics、Reactome、network pharmacology、医案分析留存代表输入/输出样例，并确认输出字段和算法版本。Reactome 当前目录实际快照已验证 2,883 条；main 的 proteomics 和医案结果黄金样例尚未提供。
- 检查旧 `tests/test_api.py` 与 `src` 业务当前是否仍可运行；保留可以复现的结果作为迁移验收样例。
- 为每个外部来源记录调用许可、限流、更新频率、引用要求和失效处理策略。
- 获取旧代码依赖的 Excel/SQLite 原始文件，并核实持有人、许可、版本、敏感字段及导入权限。

SQLite 适配器已通过合成表测试，但以上真实数据、许可和字段确认事项未完成前，不能宣称旧数据库已导入或旧业务链路已完整迁移到生产 PostgreSQL。

UniProt 官方目录同步不替代研究者历史 SQLite/Excel 数据的导入和语义核验。线上同步记录遵循来源 `2026_03` 与 SHA-256；对真实旧数据的基因别名冲突、字段对应与研究项目输出仍须以持有人提供的样本作比对。

## 生产部署差异补充

计划中的 Django、Celery、PostgreSQL、Redis、R、React/Vite 已有本地开发 Compose。公网运行另新增 `deploy/compose.production.yml`：Nginx 统一提供 HTTPS 和 React 静态页面并代理 Django；API 使用 Gunicorn 和非 root 镜像；PostgreSQL/Redis 无宿主机端口，R 只位于 worker 专用内网；上传和图表工件使用私有 S3 兼容对象存储适配。`deploy/backup-postgres.sh` 输出带 SHA-256 的 PostgreSQL dump，`deploy/restore-postgres.sh` 校验文件并要求 `--confirm` 与人工输入 `RESTORE`。S3 文件备份由对象存储提供方单独负责。Compose 配置和脚本语法已静态检查，但本机 Docker daemon 权限不可用，尚未构建或启动容器，也未实测 TLS、对象存储、PostgreSQL 迁移及恢复，因此这些属于待部署环境验收，不计作生产验收通过。
