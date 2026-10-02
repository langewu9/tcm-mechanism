# 当前架构与模块边界

## 运行结构

```text
浏览器
  └─ React + Vite（web/；开发端口 5173）
       └─ /api/* 通过开发代理转发
            └─ Django REST Framework（python_app/；开发端口 8020）
                 ├─ PostgreSQL（研究数据与溯源）
                 ├─ Redis 队列 → Celery worker（蛋白组学、数据源同步后台任务）
                 ├─ 私有媒体存储（研究者上传文件和分析工件）
                 └─ 内部隔离网络 → R Plumber（只收图表摘要 JSON）
```

开发代理已经配置；开发 Compose 中 R Plumber 只有 Celery worker 接入其私有网络，R 不挂载媒体卷、不连接 PostgreSQL，也没有宿主机公开端口。生产 Compose 另配置 Gunicorn、React 静态镜像、Nginx HTTPS、私有 S3 存储、TLS 证书挂载和服务分层网络；证书申请/续签需按部署说明自行配置。PostgreSQL 备份、校验和显式确认恢复脚本也已加入。当前环境不能访问 Docker daemon，因此这些生产容器、TLS、对象存储和恢复流程尚无实机验证。

原 `src/` Next.js 页面、组件和 CSS 尚留在仓库中供迁移参考。`web/` 当前有首页、登录/注册页、科研知识检索、医案、数据集、蛋白组学和网络药理工作台；首页沿用现有视觉样式，React Router 接管页面路由，首页统计从 Django 计数 API 获取。蛋白组学工作台沿用 main 的列映射、阈值筛选、本地靶点/通路网络及交叉验证交互；网络药理页按本地来源证据计算中药靶点与疾病靶点交集。旧研究组件并没有自动成为已接通页面；接入时要逐个核对它调用的接口和后端业务。根目录旧 Next.js `pnpm build` 目前仍失败：`src/app/page.tsx` 引用仓库中缺失的 `@/lib/prisma`；当前 Django 分支的前端构建入口是 `web/` 的 Vite build。

## 后端模块

Django 当前保留一个 `core` 应用标签和现有迁移历史，内部先按业务边界拆包：

- `apps/core/domain/sources.py`：数据源、版本、同步记录。
- `apps/core/domain/knowledge.py`：中药/成分/疾病等知识实体和带来源的证据关系。
- `apps/core/domain/research.py`：数据集、去标识化医案、医案候选、审计事件和分析任务。
- `apps/core/views/auth.py`：CSRF token、会话状态、登录和退出，以及受限速的待审核研究者注册。
- `apps/core/views/catalog.py`：知识目录查询与首页计数。
- `apps/core/views/research.py`：研究者个人工作区 API。
- `config/api_errors.py`：DRF 错误格式、Django API 404/500、CSRF 错误和请求 ID。

API 按模块分组：

| 模块 | 路径前缀 | 主要数据 |
|---|---|---|
| 认证 | `/api/v1/auth/` | 登录会话、CSRF、退出、待审核研究者注册 |
| 研究工作区 | `/api/v1/research/` | 数据集、医案、分析任务 |
| 蛋白组学 | `/api/v1/research/datasets/{id}/analyze/`、`analysis-tasks/{id}/rows/`、`analysis-tasks/{id}/export/` | 后台分析、行级 QC/映射结果、CSV/XLSX 导出 |
| 网络药理 | `/api/v1/analysis/network-pharmacology/` | 本地中药/方剂—成分—靶点和疾病—靶点证据交集、网络数据及私有任务记录；可回链到已确认的医案方剂候选 |
| R 图表 | `/api/v1/research/analysis-tasks/{id}/visualizations/`、`analysis-artifacts/{id}/download/` | 从已完成任务选取白名单图表数据，异步调用 R 并私有保存 SVG/PDF/PNG/HTML；下载按所有者授权 |
| 医案分析与审计 | `/api/v1/research/cases/{id}/analysis/`、`cases/{id}/candidates/{candidate_id}/review/`、`cases/{id}/audit/`、`cases/{id}/review/` | 需主动确认的本机模型任务、可逐字核验的结构化观察/候选、研究者逐条审核、版本化证据链和审计记录 |
| 外部分析 | `/api/v1/analysis/pathway-enrichment/`、`string-network/`；蛋白组学任务的独立同意参数 | 需要显式同意的 Reactome、STRING 物理互作和 g:Profiler GO/KEGG 富集后台任务 |
| 知识目录 | `/api/v1/catalog/` | 数据源、实体、证据关系；实体 neighborhood 最多返回 200 条活动来源关系 |
| 管理员数据源同步 | `/api/v1/admin/sources/`、`sync-runs/` | Reactome、UniProt、人工 CID 映射的 PubChem、STRING 人类标识映射与受控旧 SQLite 来源的后台预览、审计历史和人工应用 |
| 平台状态 | `/api/v1/health/` | 服务与数据库可用状态 |

模块拆分不改变现有数据库表名和迁移编号。以后模块增长到需要独立发布、权限配置或迁移边界时，再拆成独立 Django apps。

## 错误响应

所有 API 错误使用同一结构：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "提交的数据无效，请检查后重试。",
    "details": { "name": ["This field is required."] },
    "requestId": "每次请求生成的标识"
  }
}
```

`details` 用于字段级校验反馈；内部异常不向客户端暴露堆栈或数据库细节，日志使用同一个 request ID 关联排查。

## 身份和数据可见性

登录使用 Django 服务端 session，不由前端自报用户 ID。`/api/v1/auth/register/` 接收研究者账号申请，要求用户名、邮箱和符合 Django 密码校验规则的密码；新账号创建为 inactive、非 staff、非 superuser，管理员审核后才能启用。注册受 Django 与生产 Nginx 限速并强制 CSRF；邮箱所有权验证和自动通知尚未配置。后端在创建数据时填入 `request.user` 作为创建者；研究者查询仅返回本人数据，超级管理员可以查看全部。浏览器的状态变更请求会由统一 API 客户端先获取 CSRF token 并随请求发送。医案记录另外保存可核查的 `source_reference`、创建人、创建和更新时间；创建、更新、删除和审核会记录操作者、变更字段、内容 SHA-256 和时间，日志不复制医案原文。删除医案后仍保留删除审计事件。精细角色、不可变审计保护、更广文献语料/语义检索和下游任务编排仍待后续阶段实现；医案首版 RAG 只检索启用来源版本下的精确提及实体和一跳关系，并限制输入大小，知识库记录与医案原文引用分开存储、分别展示。

## 当前已接通的研究业务

- `/cases` 需要登录；未登录时会转到登录页。
- 医案页面已接通 `/api/v1/research/cases/`，支持分页查看、创建和删除。
- 医案详情操作日志通过 `/audit/` 查看；平台管理员可以审核通过并留下审核人/时间。研究者可在单条医案卡片中勾选同意，把脱敏正文、舌脉和诊断交给配置的本机/内网模型；标题、患者信息栏、来源和备注不发送。系统拒绝公网模型端点与环境 HTTP 代理，模型候选需附可在原文逐字找到的引文，并按本地规范实体精确匹配；研究者逐项确认后才展开有来源版本的本地知识关系，操作写入审计。真实模型联调、更广知识语料/语义召回和下游药理/组学任务编排仍待完成。
- `/datasets` 需要登录；支持上传 CSV/TSV/XLS/XLSX 原始文件、分页查看、权限内下载和删除。
- 症状正文保存在去标识化文本字段；患者脱敏描述、舌脉、诊断保存在结构化字段；来源和研究备注分别保存。API 返回只读提交者 ID 与用户名，便于平台管理者追溯数据责任人。
- 数据集原文件保存在私有存储适配层；开发期使用 `MEDIA_ROOT`，生产期配置私有 S3 兼容 bucket。数据库记录文件键、原文件名、大小、提交者和 SHA-256；生产对象经 Django 权限端点读取，不由 Nginx 直接公开。
- 所有医案写入由服务端绑定当前登录用户。研究者只能读取、修改或删除自己的记录；平台超级管理员可读取全部记录。
- `/proteomics` 需要登录：用户选择自己的数据集、列和筛选阈值后创建 Celery 任务；结果保留输入文件 SHA-256、算法版本、参数、请求者/数据所有者、行级 QC 和所用本地来源版本。
- 当前分析能力限于差异蛋白表的解析、基础阈值筛选、本地知识实体精确匹配、标识符格式推测（明确提示未验证）、输入候选靶点交集，以及本地已登记基因—通路证据构成的网络/degree。结果可分页查看并按 CSV/XLSX/JSON 导出。
- 研究者可分别勾选外部分析；默认关闭。MyGene.info/Reactome 链路最多处理 500 个通过筛选的人类标识；GO/KEGG 通过 g:Profiler 提供独立同意项，最多发送 500 个显著规范化符号和 25,000 个全输入表可识别符号作为自定义统计背景；STRING PPI 是另一独立同意项，最多提交 200 个规范化标识，默认置信度 700/1000，可由用户调整；在返回的物理互作图上计算唯一邻居 degree 与归一化无权 Brandes betweenness，最多处理 400 个节点、19,900 条边和 8 MiB 响应。完整上传文件、原始统计矩阵、账号和医案不发送。GO/KEGG 使用人类物种、GO 三个分支与 KEGG、FDR ≤ 0.05 多重检验校正，并在任务中记录查询/背景规模、GeneRatio、命中标识和 g:Profiler 服务/数据版本；接口拒绝跨域重定向。g:Profiler 原始未校正 p 值未由服务返回，界面明确显示只有 FDR 校正值。MyGene 精确符号先匹配，模糊多结果保留为歧义；Reactome/STRING 查询结果和可用时的数据库版本进入任务溯源。默认会先读取 STRING 当前版本，再通过官方版本专属地址查询；配置 `STRING_DB_VERSION` 可固定到指定版本。STRING 的外部 PPI 结果与本地来源网络 degree 分开展示，不混作同一指标。g:Profiler 富集请求契约由模拟测试验证；2026-10-03 使用 5 个公开合成基因符号和 25 个自定义背景标识完成一次官方 POST smoke test，返回可追溯版本但没有 FDR≤0.05 条目。这验证了连通性和协议，不替代真实项目文件与 main 输出逐项核对。
- `/admin/sources` 仅平台超级管理员可访问；Reactome 人类通路目录、UniProt 人类 reviewed 蛋白目录、PubChem 化学属性、STRING 人类标识映射和 main `backend/cache_builder.py` 生成的旧 SQLite 三表（中药—成分—靶点、疾病—靶点、疾病—中药—靶点）可在该页管理。Reactome/UniProt 预览生成 release 与 SHA-256，人工应用前复核并幂等写入；UniProt accession 与基因/蛋白别名作为独立版本化标识记录，优先关联唯一已有靶点，冲突项维持歧义。PubChem 只读取管理员在 Django Admin 配置的 CID—compound stable ID 映射，不按名称猜测；预览返回属性与差异，应用时重新读取并复核映射/响应哈希，将属性写入成分 metadata 并登记版本化 CID。STRING 连接器不下载 STRING 全量人类蛋白目录，也不新建或合并实体；它只对明确标注为人类或已有 UniProt reviewed 人类来源 ID 的本地基因/蛋白查询 STRING ID，保存版本、查询映射和 SHA-256，展示匹配样例/本地重名/归属冲突；管理员确认后幂等写入全局唯一的 STRING identifier，归属冲突不自动改绑。SQLite 只读打开配置目录内的相对路径，检查三表/列映射和文件校验值，按批次导入中药、成分、疾病、靶点及来源关系；重复来源通过唯一键更新，删除项软停用，版本、操作者、状态和计数进入审计。无任意绝对路径或连接串接口。Reactome 当前目录 2,883 条已在临时 SQLite 验证；UniProt 20,431 条已完整导入临时 SQLite 并验证重复应用幂等；PubChem PUG REST 的 6 个 main seed CID 响应已校验，1 个 CID 的预览/应用/重复预览已在一次性 SQLite 验证，临时库已删除；STRING v12.5 官方 API 的单条 TP53 标识映射实测通过，10 项模拟 connector/权限/幂等测试通过，但尚未对真实本地目录或 PostgreSQL 执行同步；PubChem 数据未写入开发或生产数据库；三表 SQLite 仅以合成表验证，真实旧库不在仓库。
- `/network-pharmacology` 需要登录；通过本地知识实体与证据关系计算中药成分靶点、疾病靶点严格交集和显式疾病—中药直接关联。每个靶点展示来源、版本、原始记录号和关系类型，结果写入当前用户的 `AnalysisTask` 并锁定所用来源版本；不会在无匹配数据时套用示例规则。本地交集本身不代表显著性富集或 PPI；单独的 Reactome 富集和 STRING 物理互作需研究者主动提交外部分析任务。
- 完成的网络药理交集任务可以请求 R 柱状图；蛋白组学 GO/KEGG 结果也能请求 R 气泡图，worker 仅发送最多 100 条经过校验的图表摘要，并在图中显示 g:Profiler 版本；HTML 产物附对应数据表。R 可产出 SVG/PDF/PNG/HTML。文件 SHA-256、输入摘要哈希和 renderer 版本均入库，可在权限检查后预览 SVG 或下载。R runtime 和 Docker image 尚未实跑，当前 Python worker 用模拟 R 响应测试私有文件持久化/下载。
- 该闭环尚未实现 Entrez 等完整稳定 ID 映射、原始矩阵统计分析、可交互网络 R 图和完整 PDF 报告；GO/KEGG 已有 g:Profiler 第一版接口、页面和 R 气泡图，仍需实时服务验收和 main 黄金样例对照。本地知识库为空时会明确显示无本地注释，不会伪称外部富集结果。蛋白组学已有独立同意后调用的 STRING 物理互作；管理员来源页也新增本地人类实体 STRING ID 交叉映射，但这不是 STRING 全量目录下载，尚未对真实项目库或 PostgreSQL 做在线验收。
- 医案智能分析已接通本机/内网模型的首版 Celery 流程，候选引文逐字核验、启用来源版本的一跳 RAG、知识引用白名单、跨来源并列展示、手动审核和来源版本证据链均有自动化测试；已确认方剂可进入网络药理工作台并形成关联回医案候选的分析任务；当前环境没有配置并运行真实模型；更广文献语料/语义召回、真实项目医案和下游药理/组学任务编排仍待完成。数据集文件上传、解析和当前蛋白组学分析也不等同于完整生信引擎。

## 后续填充顺序

1. 用 main 的实际样例和输出核对当前蛋白组学逻辑；实测 g:Profiler 并逐项确认 GO/KEGG 自定义背景/FDR 输出，然后继续补充外部稳定 ID 映射、原始矩阵分析和报告图表，并验证已接入的 STRING PPI；不得把本地网络 degree 误报为 PPI 或富集。
2. 取得旧 SQLite 文件并确认许可/字段语义后做真实数据导入验收；继续逐项验证 UniProt/PubChem/STRING 与真实项目字段，核对 STRING 人类标识映射的速率限制、冲突和 PostgreSQL 幂等应用，并完善大文件负载和失败恢复策略。
3. 在 Docker 可用环境构建并启动 R Plumber 镜像，验证锁文件、鉴权、SVG/PDF/PNG/HTML 字节和失败恢复；扩展火山图/富集/网络图及对应页面预览。
4. 先在 Docker 可用环境验证 PostgreSQL 全迁移、Celery 真实队列、R 容器、TLS、S3 读写和备份/恢复；再使用真实 main 样例逐项验收迁入业务逻辑。

当前首页、服务端会话登录、需管理员启用的研究者注册申请、本地科研知识检索及来源证据浏览、医案管理与审计/人工审核、私有数据集文件管理、第一版蛋白组学闭环、本地网络药理交集、可选 Reactome/STRING/g:Profiler 分析、Reactome/UniProt/PubChem 目录预览/应用、STRING 本地人类标识交叉映射、旧 SQLite 三表导入适配器、第一版 R 柱图任务/私有工件代码和生产部署配置已接通或完成静态配置；真实旧库验收、PubChem 人工映射的真实项目复核、STRING 整批同步与 PostgreSQL 应用验收、UniProt 与研究者真实数据字段对照、邮箱所有权验证/注册通知、g:Profiler 真实项目/黄金样例验收、原始矩阵分析、真实医案模型联调、更广 RAG 语料、容器实跑、更多交互图和生产环境验证仍未完成。首页中的研究流程文案表示目标能力，不代表当前服务已提供。
