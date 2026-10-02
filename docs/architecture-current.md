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

原 `src/` Next.js 页面、组件和 CSS 尚留在仓库中供迁移参考。`web/` 当前有首页、登录页、医案、数据集、蛋白组学和网络药理工作台；首页沿用现有视觉样式，React Router 接管页面路由，首页统计从 Django 计数 API 获取。蛋白组学工作台沿用 main 的列映射、阈值筛选、本地靶点/通路网络及交叉验证交互；网络药理页按本地来源证据计算中药靶点与疾病靶点交集。旧研究组件并没有自动成为已接通页面；接入时要逐个核对它调用的接口和后端业务。

## 后端模块

Django 当前保留一个 `core` 应用标签和现有迁移历史，内部先按业务边界拆包：

- `apps/core/domain/sources.py`：数据源、版本、同步记录。
- `apps/core/domain/knowledge.py`：中药/成分/疾病等知识实体和带来源的证据关系。
- `apps/core/domain/research.py`：数据集、去标识化医案、医案审计事件和分析任务。
- `apps/core/views/auth.py`：CSRF token、会话状态、登录和退出。
- `apps/core/views/catalog.py`：知识目录查询与首页计数。
- `apps/core/views/research.py`：研究者个人工作区 API。
- `config/api_errors.py`：DRF 错误格式、Django API 404/500、CSRF 错误和请求 ID。

API 按模块分组：

| 模块 | 路径前缀 | 主要数据 |
|---|---|---|
| 认证 | `/api/v1/auth/` | 登录会话、CSRF、退出 |
| 研究工作区 | `/api/v1/research/` | 数据集、医案、分析任务 |
| 蛋白组学 | `/api/v1/research/datasets/{id}/analyze/`、`analysis-tasks/{id}/rows/`、`analysis-tasks/{id}/export/` | 后台分析、行级 QC/映射结果、CSV/XLSX 导出 |
| 网络药理 | `/api/v1/analysis/network-pharmacology/` | 本地中药—成分—靶点和疾病—靶点证据交集、网络数据及私有任务记录 |
| R 图表 | `/api/v1/research/analysis-tasks/{id}/visualizations/`、`analysis-artifacts/{id}/download/` | 从已完成任务选取白名单图表数据，异步调用 R 并私有保存 SVG/PDF/PNG/HTML；下载按所有者授权 |
| 医案审计 | `/api/v1/research/cases/{id}/audit/`、`cases/{id}/review/` | 私有操作日志；管理员审核通过会记录操作者和时间 |
| 外部分析 | `/api/v1/analysis/pathway-enrichment/`、`string-network/` | 需要显式同意的 Reactome 富集和 STRING 物理互作后台任务 |
| 知识目录 | `/api/v1/catalog/` | 数据源、实体、证据关系 |
| 管理员数据源同步 | `/api/v1/admin/sources/`、`sync-runs/` | Reactome、UniProt 人类蛋白目录与受控旧 SQLite 来源的后台试运行、审计历史和人工应用 |
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

登录使用 Django 服务端 session，不由前端自报用户 ID。后端在创建数据时填入 `request.user` 作为创建者；研究者查询仅返回本人数据，超级管理员可以查看全部。浏览器的状态变更请求会由统一 API 客户端先获取 CSRF token 并随请求发送。医案记录另外保存可核查的 `source_reference`、创建人、创建和更新时间；创建、更新、删除和审核会记录操作者、变更字段、内容 SHA-256 和时间，日志不复制医案原文。删除医案后仍保留删除审计事件。公开研究者账号、精细角色、不可变审计保护及医案 AI/RAG 候选审核链仍需在后续阶段实现。

## 当前已接通的研究业务

- `/cases` 需要登录；未登录时会转到登录页。
- 医案页面已接通 `/api/v1/research/cases/`，支持分页查看、创建和删除。
- 医案详情操作日志通过 `/audit/` 查看；平台管理员可以审核通过并留下审核人/时间。当前还没有接入模型候选生成、证据片段对齐、方剂和下游药理链分析。
- `/datasets` 需要登录；支持上传 CSV/TSV/XLS/XLSX 原始文件、分页查看、权限内下载和删除。
- 症状正文保存在去标识化文本字段；患者脱敏描述、舌脉、诊断保存在结构化字段；来源和研究备注分别保存。API 返回只读提交者 ID 与用户名，便于平台管理者追溯数据责任人。
- 数据集原文件保存在私有存储适配层；开发期使用 `MEDIA_ROOT`，生产期配置私有 S3 兼容 bucket。数据库记录文件键、原文件名、大小、提交者和 SHA-256；生产对象经 Django 权限端点读取，不由 Nginx 直接公开。
- 所有医案写入由服务端绑定当前登录用户。研究者只能读取、修改或删除自己的记录；平台超级管理员可读取全部记录。
- `/proteomics` 需要登录：用户选择自己的数据集、列和筛选阈值后创建 Celery 任务；结果保留输入文件 SHA-256、算法版本、参数、请求者/数据所有者、行级 QC 和所用本地来源版本。
- 当前分析能力限于差异蛋白表的解析、基础阈值筛选、本地知识实体精确匹配、标识符格式推测（明确提示未验证）、输入候选靶点交集，以及本地已登记基因—通路证据构成的网络/degree。结果可分页查看并按 CSV/XLSX/JSON 导出。
- 研究者可主动勾选外部分析；默认关闭，只向 MyGene.info 发送通过筛选、未能在本地映射的最多 500 个标识，再向 Reactome 发送通过筛选的人类基因符号。完整上传文件、未通过行、账号和医案不发送。MyGene 精确符号先匹配，模糊多结果保留为歧义；映射结果、Reactome 版本和命中通路进入任务溯源。合成 TP53/IL6 联通测试已通过，尚未用真实项目文件逐项核对 main 输出。
- `/admin/sources` 仅平台超级管理员可访问；Reactome 人类通路目录、UniProt 人类 reviewed 蛋白目录和 main `backend/cache_builder.py` 生成的旧 SQLite 三表（中药—成分—靶点、疾病—靶点、疾病—中药—靶点）可在该页管理。Reactome/UniProt 预览生成 release 与 SHA-256，人工应用前复核并幂等写入；UniProt accession 与基因/蛋白别名作为独立版本化标识记录，优先关联唯一已有靶点，冲突项维持歧义。SQLite 只读打开配置目录内的相对路径，检查三表/列映射和文件校验值，按批次导入中药、成分、疾病、靶点及来源关系；重复来源通过唯一键更新，删除项软停用，版本、操作者、状态和计数进入审计。无任意绝对路径或连接串接口。Reactome 当前目录 2,883 条已在临时 SQLite 验证；UniProt 20,431 条已完整导入临时 SQLite 并验证重复应用幂等；三表 SQLite 仅以合成表验证，真实旧库不在仓库。
- `/network-pharmacology` 需要登录；通过本地知识实体与证据关系计算中药成分靶点、疾病靶点严格交集和显式疾病—中药直接关联。每个靶点展示来源、版本、原始记录号和关系类型，结果写入当前用户的 `AnalysisTask` 并锁定所用来源版本；不会在无匹配数据时套用示例规则。此版本还不做显著性富集、PPI 或因果推断。
- 完成的网络药理交集任务可以请求 R 柱状图；worker 只从任务结果选取重叠计数，R 目前产出静态 SVG/PDF/PNG/HTML。文件 SHA-256、输入摘要哈希和 renderer 版本均入库，可在权限检查后预览 SVG 或下载。R runtime 和 Docker image 尚未实跑，当前 Python worker 用模拟 R 响应测试私有文件持久化/下载。
- 该闭环尚未实现 UniProt/Entrez 完整稳定 ID 映射、GO/KEGG 富集、原始矩阵统计分析、可交互网络 R 图和完整 PDF 报告；本地知识库为空时会明确显示无本地注释，不会伪称外部富集结果。STRING PPI 目前仅在网络药理模块按需查询，尚未整合进蛋白组学 pipeline。
- 医案智能分析/候选生成仍未接通；数据集文件上传、解析和当前蛋白组学分析不等同于完整生信引擎。

## 后续填充顺序

1. 用 main 的实际样例和输出核对当前蛋白组学逻辑，再迁入外部 ID 映射、GO/KEGG 富集、PPI 和报告图表；不得把本地网络 degree 误报为 PPI 或富集。
2. 取得旧 SQLite 文件并确认许可/字段语义后做真实数据导入验收；再按许可/速率限制接入 UniProt、PubChem、STRING，并完善大文件负载和失败恢复策略。
3. 在 Docker 可用环境构建并启动 R Plumber 镜像，验证锁文件、鉴权、SVG/PDF/PNG/HTML 字节和失败恢复；扩展火山图/富集/网络图及对应页面预览。
4. 先在 Docker 可用环境验证 PostgreSQL 全迁移、Celery 真实队列、R 容器、TLS、S3 读写和备份/恢复；再使用真实 main 样例逐项验收迁入业务逻辑。

当前首页、服务端会话登录、医案管理与审计/人工审核、私有数据集文件管理、第一版蛋白组学闭环、本地网络药理交集、可选 Reactome/STRING 分析、Reactome/UniProt 目录预览/应用、旧 SQLite 三表导入适配器、第一版 R 柱图任务/私有工件代码和生产部署配置已接通或完成静态配置；真实旧库验收、PubChem/STRING 目录同步、UniProt 与研究者真实数据字段对照、账号自助注册、完整 GO/KEGG/富集图表、医案模型/RAG 候选、容器实跑、交互图和生产环境验证仍未完成。首页中的研究流程文案表示目标能力，不代表当前服务已提供。
