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
| `src/app/cases/page.tsx`、`src/components/CaseForm.tsx`、`src/app/api/cases/*` | 医案新增、列表、删除 | `/cases` + `/api/v1/research/cases/`，归属由 Django session 决定 | 创建/查看/删除 UI 已接入；API 支持更新。创建、变更、删除和平台管理员审核会追加隐私友好审计记录；本人只查看自己的记录，超级管理员可查看全部并审核。日志保存操作者、时间、字段名和内容哈希，不重复保存医案正文。完整证候/方剂 AI 候选、引文片段和逐候选确认仍未迁移 |
| `src/app/datasets/page.tsx`、`DatasetUploader.tsx`、`DeleteButton.tsx`、`src/app/api/datasets/*` | 上传 CSV/Excel、查看数据集、删除 | `/datasets` + `/api/v1/research/datasets/`，文件私有保存、带校验值和权限下载 | 私有文件 CRUD 已接入；数据集被分析任务引用后禁止替换或删除 |
| `src/lib/upload.ts` | CSV、XLS、XLSX 表格解析 | Python 解析器，限制大小/行/列/单元格、保留原始文件并生成逐行 QC | CSV/TSV/XLS/XLSX 已支持第一版解析与行数限制；尚无独立上传预览，也未做到 main 样例逐项结果对照 |
| `src/app/proteomics/page.tsx`、`ProteomicsWorkbench.tsx`、`src/lib/proteomics.ts`、`src/lib/reactome.ts`、`src/app/api/proteomics/*` | 列映射、差异蛋白阈值、MyGene 标识规范化、Reactome 富集、通路网络和候选交集 | React `/proteomics` + Django API + Celery；本地知识库映射、用户显式同意后调用 MyGene/Reactome/STRING、任务结果与来源版本持久化 | 第一版本地链路已接入：自动常见列名/手动列名、阈值/QC、显式标记未验证符号、本地实体及通路证据、候选交集、任务行记录和 CSV/XLSX/JSON 导出；MyGene/Reactome 外部调用默认关闭，最多处理 500 个通过筛选的人类标识，歧义不自动采用；STRING 物理 PPI 是另一独立同意项，最多提交 200 个标识，置信度默认 700/1000，结果单独展示并记录可用的 STRING 版本。合成数据测试通过；真实 main 样例输出核对、非人类物种、GO/KEGG、原始矩阵分析、交互图和 PDF 仍待完成 |
| `src/app/analysis/page.tsx`、`AnalysisWorkbench.tsx`、`src/lib/analysis.ts`、`src/app/api/analysis/tasks/*` | 医案/文本分析和任务结果 | Django 任务 API + Celery worker；结果和输入版本持久化 | 网络药理 API 已能将本地关系交集保存为私有任务；医案证候/方剂候选仍待实现。main 的“无匹配规则时回退到首个证候”不会照搬，以免在没有证据时虚构候选 |
| `src/app/research/page.tsx`、`ResearchWorkbench.tsx`、`src/app/api/research/route.ts` | 研究问题、证候/方剂/药物等证据链 | Django research/knowledge service 与 React 研究工作台 | 待迁移；迁移前需审查 760 行路由中的业务与外部数据依赖 |
| `src/app/api/network-pharmacology/route.ts`、`pathway-enrichment/route.ts`、`src/lib/reactome.ts`、`NetworkPharmacologyWorkbench.tsx` | 靶点交集、Reactome 富集和网络药理视图 | Django connector/service；任务固定数据源版本，页面显示证据来源 | 本地中药—成分—靶点 × 疾病—靶点交集 API/页面已接入；只按目录精确名称匹配，保存任务归属、来源版本和关系证据。用户显式同意后可异步请求 Reactome 富集和 STRING 物理互作（各有输入上限）。UniProt 本地目录作为新增迁移 connector（`main` 无同步源码）：官方 reviewed 人类目录分页同步、人工预览应用、版本化外部 identifier 已完成，20,431 条在临时 SQLite 验证幂等。PubChem PUG REST 属性 connector 也已实现，但只支持管理员人工映射 CID→本地 compound stableId；main seed 中 6 个 CID 的真实 API 响应通过校验，1 个 CID 的预览/应用/重复预览幂等已在一次性 SQLite 验证，数据未写入项目数据库。尚缺 main 黄金样例核对、Reactome/STRING 结果图形化、GO/KEGG、真实项目 CID 映射验收和 STRING 目录同步 connector |
| `src/app/admin/page.tsx`、`DatabaseSyncConsole.tsx`、`ReactomeCatalogSync.tsx`、`src/lib/database-sync.ts`、`backend/cache_builder.py` | 管理员数据源管理、测试和同步；旧缓存由中药—成分—靶点、疾病—靶点、疾病—中药—靶点三表构成 | Django Admin + 受管理员权限保护的同步 API/控制台 | Reactome 后台预览/人工应用已接入，真实目录 2,883 条已在临时 SQLite 上验证；旧 SQLite 连接器现可配置 main `cache_builder.py` 生成的三张表，预览全部实体/关系，按 SHA-256 与配置版本人工确认、批量幂等导入并软停用旧关系；UniProt 人类 reviewed 蛋白目录和 PubChem 属性读取也有版本化预览/人工应用。PubChem 必须先由管理员配置 CID→本地 compound stableId，不按名称猜测；合成三表端到端通过，6 个 main 示例 CID 响应通过校验，1 个 CID 的临时 SQLite 应用与幂等检查通过，未写入项目数据库；主机目录仅通过 `SQLITE_SOURCE_ROOT` 挂载且只读，不接受任意绝对路径。原 SQLite 文件仍不在仓库，真实字段语义和规模未核实；STRING 目录同步仍待实现 |
| `src/app/assistant/page.tsx`、`AssistantWorkspace.tsx`、`src/app/api/assistant/route.ts`、`backend/qwen_service.py` | 科研助手和 Qwen/BianCang 接口 | Django provider adapter/异步服务，前端呈现证据和模型版本 | 待迁移；不默认调用无鉴权公网模型地址。旧助手的规则回答和旧 `runAnalysis` 的任意证候回退均未照搬 |
| `src/app/api/analysis/results/*`、`src/lib/exporters.ts`、`Charts.tsx`、`NetworkGraph.tsx` | 结果、CSV/PDF 导出和图形展示 | Django 授权结果 API；React 交互图表；R 工件后续集成 | 网络药理汇总图第一版接入独立 Plumber：服务只接收白名单柱图摘要，worker 校验返回 SHA-256/文件类型，将 SVG/PDF/PNG/HTML 存入私有媒体并通过 Django 所有者权限下载。合成响应测试覆盖任务排队、跨用户隔离、散列与下载。R/Docker 镜像未能实跑，交互图、proteomics 全图表、main 对照结果和下载量/超时生产压测仍缺 |

## main 中的重要数据对象

`prisma/schema.prisma`（SQLite）主要包含：

- 账号与归属：`User`、`Dataset`、`MedicalCase`、`AnalysisTask`。
- 文件/表格：`DatasetRow`、`ProteomicsDataset`、`ProteomicsRow`、`ProteomicsAnalysis`。
- 研究知识：`Syndrome`、`Formula`、`Herb`、`Compound`、`Target`、`Gene`、`Pathway`。
- 结果与来源：`AnalysisResult`、`PathwayEnrichmentRun`、`PathwayEnrichmentItem`、`DatabaseSource`、`DatabaseSyncRun`。

当前 Django 已有 `ResearchDataset`、`MedicalCase`、`MedicalCaseAuditEvent`、`AnalysisTask`、`VisualizationArtifact`、`KnowledgeEntity`、`EvidenceRelation`、`DataSource`、`SourceRelease` 和 `SyncRun`。迁移时要优先做字段映射：例如 main 的多个知识实体表映射到 Django 的实体类型/规范 ID；main `DatasetRow` 不应无界转成 JSON 表；蛋白组学的行级结果、输入文件、任务、结果及图表工件需要明确模型边界和容量策略。

### 首版字段映射

| main SQLite/Prisma 对象 | Django/PostgreSQL 映射方向 | 需要保留或转换的内容 |
|---|---|---|
| `User` | Django `AUTH_USER_MODEL` | main 的字符串 CUID 与 Django 主键不同；导入时需做稳定 ID/email 对照，密码 hash 格式须验证，角色不得直接信任 |
| `Dataset` | `ResearchDataset` | 名称、说明、上传人、文件名；新系统另记私有 storage key、SHA-256 和字节数 |
| `DatasetRow` | 暂不直接映射 | 当前不向数据库无界写行 JSON；要按分析用途设计受控导入/分块与原始文件追溯 |
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
