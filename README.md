# 岐黄中医药理智能平台

本仓库正在按《技术栈与阶段实施计划》迁移为面向公网研究者使用的 Django 平台。目标是保留并逐步重写已有业务能力，由 Django 统一承担网页、登录、权限和 API；PostgreSQL 保存研究数据与溯源信息，本地模型及分析服务按计划逐项接入。

## 当前架构

- 主站与 API：`python_app/`，Django 5.2、Django REST Framework。
- 数据库：PostgreSQL；本地自动化测试可使用 SQLite。
- 登录：Django 服务端会话与 CSRF 防护。
- 研究者创建的数据集、医案和分析任务按所属用户隔离；平台超级管理员可通过管理后台及 API 查看全部记录。
- 数据集、医案和任务保留创建者外键；存在这些记录时，数据库会阻止直接删除用户，以免丢失数据和溯源关系。

旧的 Next.js、FastAPI、Prisma 和桌面程序代码仍在仓库中，但只作为提取和重写业务功能时的参考材料，不属于目标运行架构。不要按照旧目录中的说明启动或部署旧服务。迁移应把确认需要的功能逐项实现到 Django，并逐项验证。

## 已有与待完成

当前 Django 骨架包含登录页面、Django 管理后台、数据源/版本/证据模型、实体关系查询，以及按用户隔离的数据集、医案和分析任务 API。分析任务目前只能查看记录，尚没有实际任务执行器。

文件上传和对象存储、Celery/Redis、外部数据库同步、蛋白组学分析、医案候选生成、R Plumber 绘图、本地模型接入、审计日志和生产部署仍未完成。当前版本是迁移中的基础骨架，不可视作已经上线的完整研究平台。历史 SQLite、Excel 和其他文件不会被自动导入；迁移前需做数据清单、字段映射和备份。

总体实施路线见 [`docs/技术栈与阶段实施计划.md`](docs/技术栈与阶段实施计划.md)，Python 到 R 的图表数据约定见 [`docs/r-visualization-contract.md`](docs/r-visualization-contract.md)。

## Linux 本地开发

需要 Python 3.12+ 和 Docker Compose。先在仓库根目录启动开发用 PostgreSQL：

```bash
docker compose -f deploy/compose.python.yml up -d postgres
```

再在 `python_app/` 目录执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8020
```

打开 `http://127.0.0.1:8020/`、`/admin/`、`/api/v1/` 或 `/api/docs/`。`.env.example` 里的数据库密码只用于本地开发；不要把 `.env` 或真实密钥提交到 Git。

运行检查与测试：

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

## 目录

- `python_app/`：当前 Django 主应用。
- `docs/`：技术路线和服务接口约定。
- `src/`、`backend/`、`prisma/`、`frontend/`：迁移时按需查阅的旧实现；不会作为 Django 平台的运行依赖。
