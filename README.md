# 岐黄中医药理智能平台

本仓库正在把已确认的研究平台能力迁移到 **React/Vite 前端 + Django REST Framework 后端**。研究业务和账号由 Django 统一处理，研究数据目标为 PostgreSQL；医案本机/内网模型适配已有首版，但须由部署者提供并配置实际模型服务。

## 当前架构

最新本地修补、服务启动、验收结果与待接依赖见 [`docs/local-acceptance-2026-10-19.md`](docs/local-acceptance-2026-10-19.md)；研究资料归档规则见 [`docs/research-retention.md`](docs/research-retention.md)。

原表到目录、接口和图表的逐层核对及映射修正见 [`docs/data-consistency-2026-10-19.md`](docs/data-consistency-2026-10-19.md)。

- `web/`：独立的 React + TypeScript + Vite 前端。首页复用了现有 Next 页面结构和样式，新增了 Django 会话登录入口。
- `python_app/`：Django 5.2 + Django REST Framework API、服务端会话认证、权限和管理后台。代码按认证、知识目录和研究工作区分模块。
- `deploy/compose.python.yml`：本地 PostgreSQL 开发服务。
- 研究数据集、医案和分析任务按所属用户隔离；平台超级管理员可查看所有人的记录。每条记录保留创建者外键，避免删除用户时失去溯源关系。

旧的 Next.js、FastAPI、Prisma 和桌面程序代码暂留在仓库作为提取业务规则的参考。它们尚未逐页接入新的 React 应用，也不是新 Django 平台的运行依赖。页面外观沿用旧首页 CSS；旧研究模块要在逐项迁移后才会成为可用页面。

## 当前已有与待补齐

当前已有公开首页、登录 API、健康检查、知识库规模统计、知识实体/来源证据查询、按用户隔离的数据集与医案 API、分析任务记录和 Django 管理后台。API 错误统一返回 `error.code`、`error.message`、`error.details` 和 `error.requestId`。分析任务已用于运行蛋白组学、数据源同步、网络药理和图表后台链路；医案分析首版也可排入 Celery，但需要部署者提供本机/内网模型端点。

项目仍在迁移完善中：完整 RAG、医案下游药理/组学编排、原始定量矩阵分析、真实旧库导入和 PostgreSQL/R/S3 生产环境验收尚未完成。医案本机模型候选、人工逐项复核和来源证据链已有首版；真实模型由部署者配置。现有数据文件不会自动导入 PostgreSQL。

架构边界、接口分组和下一步迁移入口见 [`docs/architecture-current.md`](docs/architecture-current.md)。

## Linux 本地开发

需要 Python 3.12+、Node.js 和 Docker Compose。先在仓库根目录启动 PostgreSQL：

```bash
docker compose -f deploy/compose.python.yml up -d postgres
```

在终端一启动 Django（`python_app/` 目录）：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8020
```

在终端二启动 React（仓库根目录）：

```bash
cd web
pnpm install
pnpm dev
```

打开 Vite 地址（通常为 `http://127.0.0.1:5173/`）。开发服务器会把 `/api/`、`/django-admin/` 和 `/accounts/` 代理给 Django 的 `8020` 端口；`/admin/` 保留给 React 管理页面。前后端尚未配置公网反向代理，不能据此直接部署。

检查 Django：

```bash
cd python_app
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

不连接 PostgreSQL 时，可用 SQLite 跑 Django 逻辑测试：

```bash
DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: python manage.py test
```

`.env.example` 中的密码仅供本地开发；不要把 `.env` 或真实密钥提交到 Git。
