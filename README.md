# 远志 AI Scientist

中医药理研究平台。当前运行栈由 React/Vite 前端、Django REST API、R 绘图服务和 Docker 数据库/任务服务组成。

## 核心目录

- `web/`：React、TypeScript、Vite 前端；本机开发地址为 `http://127.0.0.1:5173/`。
- `python_app/`：Django REST Framework、管理后台、知识目录、医案和组学任务。
- `r_viz/`：R 图表渲染服务及经过审核的演示图素材。
- `deploy/`：原数据库启动、开发/生产 Docker Compose、Nginx、备份与恢复配置。
- `tools/`：当前数据核验、服务验收和数据库维护脚本。
- `docs/`：当前启动手册、数据规范和模块操作说明。

## 启动

Windows 本地使用原 SQLite 数据库时，运行项目根目录的 `start-all-services.cmd`。它会启动或复用 Docker、Django、Redis、R 绘图服务、任务队列和 Vite 前端，并检查服务状态。

- [Windows 启动手册](docs/Windows启动手册.md)
- [原数据库 Docker 说明](docs/原数据库Docker启动说明.md)
- [生产部署说明](deploy/README-production.md)

开发环境的 PostgreSQL Compose 位于 `deploy/compose.python.yml`；本机原 SQLite 数据库启动使用 `deploy/compose.original-sqlite.yml`。两者数据卷不同，不要混用启动命令。

## 当前结构

```text
浏览器 → React/Vite → Django REST API
                         ├─ SQLite（本机原库）或 PostgreSQL
                         ├─ Redis → Celery 分析任务
                         └─ 内部网络 → R 绘图服务
```

完整组件边界见[当前架构说明](docs/architecture-current.md)。靶点身份与物种核验见[最新数据核验记录](docs/target-species-and-project-data-audit-2026-11-03.md)。

## 开发

Python 依赖清单在 `python_app/requirements.txt`，前端使用 `web/pnpm-lock.yaml`。本地环境变量模板为 `python_app/.env.example`；生产模板为 `.env.production.example`。真实数据库、研究数据、模型文件、证书和密钥不应提交到仓库。

GitHub Actions 在 `.github/workflows/platform-checks.yml` 中分别检查 Django、SQLite/PostgreSQL 逻辑以及 Vite 前端。
