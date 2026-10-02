# main 分支代码迁移盘点

盘点基线：`origin/main`，提交 `078d374`（2026-10-02）。当前目标分支：`codex/django-foundation-hardening`。本文把 main 当作页面、业务算法和数据字段的参考来源；不合并整条分支，逐个模块移植到 Django + React/Vite 后通过测试再启用。

## 迁移规则

- React 组件和 CSS 可以复用交互与视觉结构，但 `next/navigation`、Next.js Server Actions、Prisma 查询必须改为 React Router、Django API 和当前设计系统。
- 领域算法优先复用并迁到 Python 业务服务，需建立输入/输出样例并与 main 结果对照后才能替换旧路径。
- 旧版数据使用 Prisma/SQLite，Django 使用 PostgreSQL 和新表结构。只迁字段含义，不直接复制 SQLite 表或未经盘点的数据。
- 登录使用 Django 服务端 session 和 CSRF。旧项目的 Cookie/JWT 解析、内置默认管理员密码和角色逻辑不作为新系统鉴权实现。
- 旧 API 若依赖 Windows 固定路径、`data_cache.db`、Excel 本地文件、公开模型地址或 SQLite，应先抽出领域逻辑和数据契约，再改造成配置化服务。

## 页面与业务迁移映射

| main 分支源码 | main 中的用途 | 当前 Django + React/Vite 目标 | 状态 |
|---|---|---|---|
| `src/components/AppShell.tsx`、`AppNavigation.tsx`、`PageHeader.tsx`、`src/app/product.css` | 主导航、页面框架和产品视觉样式 | `web/src` 中复用样式/交互，路由改为 React Router | 首页、医案和数据集已接入；通用工作台导航待整理 |
| `src/app/cases/page.tsx`、`src/components/CaseForm.tsx`、`src/app/api/cases/*` | 医案新增、列表、删除 | `/cases` + `/api/v1/research/cases/`，归属由 Django session 决定 | 已接入；目前页面支持创建/查看/删除，API 保留更新能力 |
| `src/app/datasets/page.tsx`、`DatasetUploader.tsx`、`DeleteButton.tsx`、`src/app/api/datasets/*` | 上传 CSV/Excel、查看数据集、删除 | `/datasets` + `/api/v1/research/datasets/`，文件私有保存、带校验值和权限下载 | 原文件 CRUD 已接入；解析、行预览和 QC 待蛋白组学阶段 |
| `src/lib/upload.ts` | CSV、XLS、XLSX 表格解析 | Python 上传解析服务，复用样例和字段意图；限制行数、校验列并保留原始文件 | 待迁移；当前上传只保存原文件，不同步插入未经验证的行 |
| `src/app/proteomics/page.tsx`、`ProteomicsWorkbench.tsx`、`src/lib/proteomics.ts`、`src/app/api/proteomics/*` | 列映射、差异蛋白阈值、标准化、富集/网络结果 | React 页面接 Django 的 proteomics API；算法落 Python worker/service | 待迁移；先建立 CSV/XLSX 黄金样例和 main 结果基准 |
| `src/app/analysis/page.tsx`、`AnalysisWorkbench.tsx`、`src/lib/analysis.ts`、`src/app/api/analysis/tasks/*` | 医案/文本分析和任务结果 | Django 任务 API + Celery worker；结果和输入版本持久化 | 待迁移；当前 AnalysisTask 是只读记录，还没有执行器 |
| `src/app/research/page.tsx`、`ResearchWorkbench.tsx`、`src/app/api/research/route.ts` | 研究问题、证候/方剂/药物等证据链 | Django research/knowledge service 与 React 研究工作台 | 待迁移；迁移前需审查 760 行路由中的业务与外部数据依赖 |
| `src/app/api/network-pharmacology/route.ts`、`pathway-enrichment/route.ts`、`src/lib/reactome.ts`、`NetworkPharmacologyWorkbench.tsx` | 靶点交集、Reactome 富集和网络药理视图 | Django connector/service；任务固定数据源版本，页面显示证据来源 | 待迁移；需先验证外部 API 限流、许可和版本语义 |
| `src/app/admin/page.tsx`、`DatabaseSyncConsole.tsx`、`ReactomeCatalogSync.tsx`、`src/lib/database-sync.ts` | 管理员数据源管理、测试和同步 | Django Admin + 受管理员权限保护的同步 API/控制台 | 待迁移；不暴露原始连接串和密钥 |
| `src/app/assistant/page.tsx`、`AssistantWorkspace.tsx`、`src/app/api/assistant/route.ts`、`backend/qwen_service.py` | 科研助手和 Qwen/BianCang 接口 | Django provider adapter/异步服务，前端呈现证据和模型版本 | 待迁移；不默认调用无鉴权公网模型地址 |
| `src/app/api/analysis/results/*`、`src/lib/exporters.ts`、`Charts.tsx`、`NetworkGraph.tsx` | 结果、CSV/PDF 导出和图形展示 | Django 授权结果 API；React 交互图表；R 工件后续集成 | 待迁移 |

## main 中的重要数据对象

`prisma/schema.prisma`（SQLite）主要包含：

- 账号与归属：`User`、`Dataset`、`MedicalCase`、`AnalysisTask`。
- 文件/表格：`DatasetRow`、`ProteomicsDataset`、`ProteomicsRow`、`ProteomicsAnalysis`。
- 研究知识：`Syndrome`、`Formula`、`Herb`、`Compound`、`Target`、`Gene`、`Pathway`。
- 结果与来源：`AnalysisResult`、`PathwayEnrichmentRun`、`PathwayEnrichmentItem`、`DatabaseSource`、`DatabaseSyncRun`。

当前 Django 已有 `ResearchDataset`、`MedicalCase`、`AnalysisTask`、`KnowledgeEntity`、`EvidenceRelation`、`DataSource`、`SourceRelease` 和 `SyncRun`。迁移时要优先做字段映射：例如 main 的多个知识实体表映射到 Django 的实体类型/规范 ID；main `DatasetRow` 不应无界转成 JSON 表；蛋白组学的行级结果、输入文件、任务、结果及图表工件需要明确模型边界和容量策略。

### 首版字段映射

| main SQLite/Prisma 对象 | Django/PostgreSQL 映射方向 | 需要保留或转换的内容 |
|---|---|---|
| `User` | Django `AUTH_USER_MODEL` | main 的字符串 CUID 与 Django 主键不同；导入时需做稳定 ID/email 对照，密码 hash 格式须验证，角色不得直接信任 |
| `Dataset` | `ResearchDataset` | 名称、说明、上传人、文件名；新系统另记私有 storage key、SHA-256 和字节数 |
| `DatasetRow` | 暂不直接映射 | 当前不向数据库无界写行 JSON；要按分析用途设计受控导入/分块与原始文件追溯 |
| `MedicalCase` | `MedicalCase` | `symptoms` → `deidentified_text`；`patientInfo/tonguePulse/diagnosis` → `structured_data`；`source` → `source_reference`；记录用户和时间 |
| `AnalysisTask` / `AnalysisResult` | `AnalysisTask` + 待设计结果/工件模型 | 输入医案、参数、状态、证据、网络、算法/来源版本分别建模；不能把历史 `COMPLETED` 假设成新任务状态 |
| `ProteomicsDataset` / `ProteomicsRow` / `ProteomicsAnalysis` | 待设计 `proteomics` 与 `analysis` 数据模型 | 原始文件、列映射、原始标签、规范基因 ID、阈值、未映射/排除记录、结果和来源版本均可复核 |
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
- 为 proteomics、Reactome、network pharmacology、医案分析留存代表输入/输出样例，并确认输出字段和算法版本。
- 检查旧 `tests/test_api.py` 与 `src` 业务当前是否仍可运行；保留可以复现的结果作为迁移验收样例。
- 为每个外部来源记录调用许可、限流、更新频率、引用要求和失效处理策略。
- 获取旧代码依赖的 Excel/SQLite 原始文件，并核实持有人、许可、版本、敏感字段及导入权限。

以上事项未完成前，不能宣称旧业务链路已完整迁移或旧数据库可直接导入生产 PostgreSQL。
