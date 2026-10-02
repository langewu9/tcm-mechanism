# Django API 后端

`python_app/` 提供认证、权限、研究数据 API、管理后台和蛋白组学分析任务。React 前端位于仓库根目录的 `web/`；本地开发时 Vite 在 `5173` 端口，将 `/api/` 代理到 Django `8020` 端口。`deploy/compose.python.yml` 用于本地开发；`deploy/compose.production.yml` 提供 Gunicorn、HTTPS Nginx、私有对象存储和分层网络的生产部署起点，尚未在实际服务器上运行验收。

## Linux 本地启动

要求 Python 3.12+ 和 Docker Compose。仓库根目录启动 Django API、PostgreSQL、Redis 和 Celery worker：

```bash
docker compose -f deploy/compose.python.yml up -d --build
```

Compose 中的密钥只用于本机开发。前端开发服务器单独在 `web/` 目录启动：

```bash
pnpm dev --host 127.0.0.1
```

React/Vite 使用同源代理把 `/api/` 请求转发到 Django `127.0.0.1:8020`。

首次启动后，可在仓库根目录新开终端创建 Django 超级管理员：

```bash
docker compose -f deploy/compose.python.yml exec api python manage.py createsuperuser
```

也可以在主机上启动 Django API 和 Celery worker。先只启动数据库与 Redis：

```bash
docker compose -f deploy/compose.python.yml up -d postgres redis
cd python_app
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8020
```

另开终端启动 worker：

```bash
cd python_app
source .venv/bin/activate
celery -A config worker --loglevel=INFO
```

后端独立运行时根路径跳转到 `/api/docs/`。

## API 模块

- `GET /api/v1/health/`：应用与数据库健康状态。
- `GET /api/v1/home-stats/`：公开首页显示的知识目录计数。
- `/api/v1/auth/csrf/`、`/api/v1/auth/session/`：Django 会话登录、状态查询和退出。
- `/api/v1/research/datasets/`、`cases/`、`analysis-tasks/`：研究者工作区记录。研究者只访问自己的数据，超级管理员可看全部。
- 医案支持私有审计查询 `GET /api/v1/research/cases/{id}/audit/`；平台管理员可显式 `POST /api/v1/research/cases/{id}/review/`（`{"decision":"approve"}`）标记审核。审计日志保留操作人、时间、变更字段与内容哈希，不重复存储医案正文。
- `POST /api/v1/research/datasets/{id}/analyze/`：将已保存的数据集排入 Celery，创建有归属和原文件 SHA-256 的分析任务。
- `GET /api/v1/research/analysis-tasks/{id}/rows/`：分页读取蛋白组学行级筛选、映射和排除原因；支持 `?selected=true` / `?selected=false`。
- `GET /api/v1/research/analysis-tasks/{id}/export/?file_format=csv|xlsx`：按任务所有者权限导出所有行级结果；CSV/XLSX 会转义公式型用户输入。
- `POST /api/v1/research/analysis-tasks/{id}/visualizations/`（`{"chartKey":"overlap"}`）：从已完成的网络药理任务排入 R 柱图任务；蛋白组学支持 `proteomics_summary` 与 `proteomics_top_nodes`。`GET /api/v1/research/analysis-artifacts/{id}/download/` 提供所有者权限保护的工件，SVG/PNG 可通过 `?inline=1` 安全预览。当前第一版限制为最多 100 个图点，R 只收到图表摘要 JSON，不收到医案原文或完整文件；产出 SVG/PDF/PNG/HTML。
- 蛋白组学请求可传 `externalReactome: true`；只有用户明确启用时才调用 MyGene.info 和 Reactome，外部标识最多 500 个，且只包含通过筛选的基因/蛋白标签。默认 `false`；当前外部流程仅支持人类标识。
- `/api/v1/catalog/sources/`、`entities/`、`evidence/`：外部数据源、规范实体和来源证据目录。
- 用户显式同意后，`POST /api/v1/analysis/pathway-enrichment/` 将最多 500 个标识发送至 Reactome，`POST /api/v1/analysis/string-network/` 将最多 200 个标识提交至 STRING 查询物理互作；两者均异步记录到私有分析任务。STRING 查询会自动发现数据库版本并调用版本专属地址；可通过 `STRING_DB_VERSION` 固定版本，结果和版本来源均写入任务记录。
- `/api/v1/admin/sources/`、`/api/v1/admin/sync-runs/`：超级管理员可用的数据源清单与同步审计；`POST /api/v1/admin/sources/{id}/test/` 测试受控 SQLite 来源；`POST /api/v1/admin/sources/{id}/sync/` 创建 Reactome、UniProt 人类 reviewed 蛋白目录、PubChem 成分属性或 SQLite 预览，`POST /api/v1/admin/sync-runs/{preview_id}/apply/` 再人工确认应用。UniProt 记录页数、release header、SHA-256 和总数校验，accession/基因/蛋白别名有独立来源版本；只有唯一匹配的基因符号才会关联到本地已有靶点。PubChem 只接受 Django Admin 中人工确认的 CID→本地成分 stableId 映射；配置键为 `configuration.mappings`，每项形如 `{"stableId":"local-compound-id","cid":"5280343"}`，不会按名称猜测。
- 同一管理页也支持登记 main `backend/cache_builder.py` 生成的 SQLite 缓存。默认映射对应 `herb_component_target`、`disease_target`、`disease_herb_target` 三张表；实际结构不同可调整表名和列名。Compose 将仓库外的 `var/source-databases/` 只读挂载到 worker；先把获准使用的数据库文件放在那里，再在 `/admin/sources` 登记相对文件名和字段映射，测试连接后预览并确认导入。API 不接受绝对路径，配置和主机目录不会发回浏览器；在主机上运行 Django 时，把 `SQLITE_SOURCE_ROOT` 指向受控目录。
- `/api/schema/`、`/api/docs/`：OpenAPI schema 与交互式文档。

API 错误统一使用 `{ "error": { "code", "message", "details", "requestId" } }`。Django 服务端会话使用 HttpOnly Cookie，改变数据的请求需要 CSRF token；客户端提交的 `owner` 字段不会被信任。数据集、医案和任务记录保留创建者外键，账号有关联记录时不能直接硬删除。

## 检查与测试

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

没有 PostgreSQL 时可用 SQLite 测逻辑：

```bash
DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: python manage.py test
```

## 生产部署与数据保护

生产环境变量、证书准备、启动、日志和备份/恢复流程见仓库根目录的 [`deploy/README-production.md`](../deploy/README-production.md)。生产上传文件通过 S3 兼容私有 bucket 保存；本地开发和测试仍使用受控 `MEDIA_ROOT`。备份 PostgreSQL 不会备份对象文件，需要在对象存储提供方另行配置版本管理或副本。

## 尚未实现

研究数据集支持上传、私有下载和删除，开发和测试时默认保存于 `MEDIA_ROOT`，单个文件上限由 `DATASET_UPLOAD_MAX_BYTES` 控制（默认 100 MiB）；生产环境使用私有 S3 兼容对象存储并通过 Django 授权端点传输。蛋白组学已支持 CSV/TSV/XLS/XLSX 解析、常见列名识别、基础阈值/QC、本地实体映射、UniProt accession 别名、本地来源通路网络、候选靶点交集、Celery 后台任务和 CSV/XLSX/JSON 结果导出；用户主动启用时还可调用 MyGene.info 和 Reactome（最多 500 个通过筛选的人类标识，默认关闭）。另有独立的 STRING PPI 同意项（最多 200 个标识，置信度默认 700/1000），结果与本地网络 degree 分开呈现；默认自动发现 STRING 当前版本并请求版本专属 API 地址，配置 `STRING_DB_VERSION` 可显式固定服务版本。网络药理交集页也支持用户主动同意后的 Reactome 富集（最多 500 标识）和 STRING 物理互作查询（最多 200 标识）；管理员来源页还可预览/应用 STRING 人类 ID 交叉映射，只处理本地已有人类实体，不下载完整 STRING 蛋白目录、不创建或合并知识实体。STRING v12.5 的单条 TP53 官方 API 映射已实测通过；真实本地目录整批应用和 PostgreSQL 验收尚未完成。网络交集和蛋白组学汇总可请求受控 R 静态柱图；Plumber 服务仅接收服务端白名单摘要数据，工件保存在私有存储并受 Django 用户权限保护。开发 Compose 内 R 服务仅接在 worker 专用隔离网络，未公开宿主端口。R 容器目前未能实际构建或运行；前端预览、后端权限和工件写入只通过模拟响应验收。Reactome 2,883 条已在临时 SQLite 验证；UniProt release `2026_03` 的 20,431 条已完整导入临时 SQLite，82,588 条标识记录在重复应用后仍保持幂等；PubChem PUG REST 已真实读取 main seed 中 6 个 CID，并在一次性 SQLite 验证 1 个 CID 的真实预览、应用和幂等；临时库已删除，未写入项目数据库；实际研究数据字段语义和 PostgreSQL 生产数据库尚未验收。当前仍不做 GO/KEGG、原始矩阵统计分析或交互式 R 网络图。PubChem 映射尚未用真实研究项目成分核实；STRING 真实本地目录整批映射、模型生成的医案证候/方剂候选和本地模型接入仍未实现。生产部署所需的网络拓扑、TLS 代理、私有对象存储适配和 PostgreSQL 备份/恢复脚本已有配置，但 Docker/PostgreSQL、TLS、S3 读写和备份恢复尚未实机验证。SQLite 测试不代替 PostgreSQL 环境验证。
