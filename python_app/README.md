# Django API 后端

`python_app/` 提供认证、权限、研究数据 API 和管理后台。React 前端位于仓库根目录的 `web/`；本地开发时 Vite 在 `5173` 端口，将 `/api/` 代理到此服务的 `8020` 端口。生产反向代理和容器编排仍待完成。

## Linux 本地启动

要求 Python 3.12+ 和 Docker Compose。仓库根目录启动本地 PostgreSQL：

```bash
docker compose -f deploy/compose.python.yml up -d postgres
```

在 `python_app/` 目录：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8020
```

后端独立运行时根路径跳转到 `/api/docs/`；研究者前端由 `web/` 提供。

## API 模块

- `GET /api/v1/health/`：应用与数据库健康状态。
- `GET /api/v1/home-stats/`：公开首页显示的知识目录计数。
- `/api/v1/auth/csrf/`、`/api/v1/auth/session/`：Django 会话登录、状态查询和退出。
- `/api/v1/research/datasets/`、`cases/`、`analysis-tasks/`：研究者工作区记录。研究者只访问自己的数据，超级管理员可看全部。
- `/api/v1/catalog/sources/`、`entities/`、`evidence/`：外部数据源、规范实体和来源证据目录。
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

文件上传、对象存储、自助注册、异步分析执行、外部数据同步、蛋白组学与医案候选流程、R 绘图、本地模型接入、审计日志、公网安全加固和生产反向代理仍在后续阶段。SQLite 测试不代替 PostgreSQL 环境验证。
