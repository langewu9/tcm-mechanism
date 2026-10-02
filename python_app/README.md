# Django API 后端

`python_app/` 提供认证、权限、研究数据 API、管理后台和蛋白组学分析任务。React 前端位于仓库根目录的 `web/`；本地开发时 Vite 在 `5173` 端口，将 `/api/` 代理到 Django `8020` 端口。当前 Compose 仅用于本地开发，生产反向代理和部署加固仍待完成。

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
- `POST /api/v1/research/datasets/{id}/analyze/`：将已保存的数据集排入 Celery，创建有归属和原文件 SHA-256 的分析任务。
- `GET /api/v1/research/analysis-tasks/{id}/rows/`：分页读取蛋白组学行级筛选、映射和排除原因；支持 `?selected=true` / `?selected=false`。
- `GET /api/v1/research/analysis-tasks/{id}/export/?file_format=csv|xlsx`：按任务所有者权限导出所有行级结果；CSV/XLSX 会转义公式型用户输入。
- 蛋白组学请求可传 `externalReactome: true`；只有用户明确启用时才调用 MyGene.info 和 Reactome，外部标识最多 500 个，且只包含通过筛选的基因/蛋白标签。默认 `false`；当前外部流程仅支持人类标识。
- `/api/v1/catalog/sources/`、`entities/`、`evidence/`：外部数据源、规范实体和来源证据目录。
- `/api/v1/admin/sources/`、`/api/v1/admin/sync-runs/`：超级管理员可用的数据源清单与同步审计；`POST /api/v1/admin/sources/{id}/test/` 测试受控 SQLite 来源；`POST /api/v1/admin/sources/{id}/sync/` 创建 Reactome 或 SQLite 预览，`POST /api/v1/admin/sync-runs/{preview_id}/apply/` 再人工确认应用。
- 同一管理页也支持登记旧版 SQLite 中药—成分—靶点表。Compose 将仓库外的 `var/source-databases/` 只读挂载到 worker；先把获准使用的数据库文件放在那里，再在 `/admin/sources` 登记相对文件名、表名和三列映射，测试连接后预览并确认导入。API 不接受绝对路径，配置和主机目录不会发回浏览器；在主机上运行 Django 时，把 `SQLITE_SOURCE_ROOT` 指向受控目录。
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

## 尚未实现

研究数据集支持上传、私有下载和删除，默认保存于 `MEDIA_ROOT`，单个文件上限由 `DATASET_UPLOAD_MAX_BYTES` 控制（默认 100 MiB）；部署时不得通过静态 Web 服务器直接公开该目录。蛋白组学已支持 CSV/TSV/XLS/XLSX 解析、常见列名识别、基础阈值/QC、本地实体映射、来源关联通路网络、候选靶点交集、Celery 后台任务和 CSV/XLSX/JSON 结果导出；用户主动启用时还可调用 MyGene.info 和 Reactome（最多 500 个通过筛选的人类标识，默认关闭）。Reactome 目录和旧版 SQLite 中药—成分—靶点表均由超级管理员在 `/admin/sources` 预览差异后确认应用，保存版本、SHA-256、操作者和运行状态；SQLite 文件受控目录只读挂载、校验路径与字段名，不会从浏览器传入绝对路径。两种来源分别通过真实 Reactome 当前目录（2,883 条，临时 SQLite）和合成旧版表完成端到端 preview/apply 测试；不代表旧研究数据库已实际交付，也不代表 PostgreSQL 生产验收。当前仍不做 GO/KEGG 富集、STRING PPI 或原始矩阵统计分析。对象存储适配、自助注册、UniProt/PubChem/STRING 来源同步、医案候选流程、R 绘图、本地模型接入、公网安全加固和生产反向代理仍在后续阶段。SQLite 测试不代替 PostgreSQL 环境验证。
