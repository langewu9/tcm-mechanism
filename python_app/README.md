# Django 主站（迁移第一阶段）

`python_app/` 是平台的目标主应用，负责网页、登录、权限和 API。仓库中的 Next.js、FastAPI、Prisma 和桌面程序只作为迁移时提取业务逻辑的参考，不是本应用的运行依赖。后续按 [`../docs/技术栈与阶段实施计划.md`](../docs/技术栈与阶段实施计划.md) 逐项重写并验证原有业务。

## Linux 本地启动

要求 Python 3.12+ 和 Docker Compose。先在仓库根目录启动本地 PostgreSQL：

```bash
docker compose -f deploy/compose.python.yml up -d postgres
```

然后在 `python_app/` 目录执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8020
```

访问 `http://127.0.0.1:8020/`、`/admin/`、`/api/v1/` 和 `/api/docs/`。开发数据库密码不可用于公网部署；生产环境必须配置独立数据库凭据、`DJANGO_SECRET_KEY`、允许的主机名和 CSRF 来源。

## 检查与测试

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

不连接 PostgreSQL时，可在 Linux/macOS 下用 SQLite 执行自动化测试：

```bash
DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: python manage.py test
```

SQLite 测试只能验证 Django 逻辑，不能替代 PostgreSQL 部署验证。

## 第一阶段接口

- `GET /api/v1/health/`：检查应用和数据库连通状态。
- `GET /api/schema/`、`/api/docs/`：OpenAPI schema 与接口文档。
- `/api/v1/datasets/`：数据集元信息 CRUD；当前用户只访问自己的记录，超级管理员可以查看全部。
- `/api/v1/cases/`：去标识化医案 CRUD；当前用户只访问自己的记录，超级管理员可以查看全部。
- `/api/v1/analysis-tasks/`：分析任务只读记录；结果仅对任务所属用户和超级管理员可见。
- `/api/v1/sources/`、`/entities/`、`/evidence/`：已启用数据源、规范实体和来源证据只读查询。

用户身份由 Django 登录会话在服务端确认，不信任客户端提交的 `owner` 字段。数据集、医案和任务记录关联创建者；只要账号仍有关联记录，硬删除账号会被数据库拒绝，以免丢失研究数据及来源追溯关系。后续应提供停用账号或经审批的匿名化流程，而不是级联清除数据。

数据源证据使用 `SourceRelease` 和 `source_record_id` 记录版本及来源记录标识。医案字段只接受去标识化文本；系统暂未实现自动去标识化。

## 尚未实现

- 实际文件上传、对象存储及上传格式校验。
- Celery/Redis 任务执行、取消、重试和完整错误追踪。
- 外部数据 connector、定时同步和管理员同步控制台。
- 蛋白组学导入/QC/富集/PPI，医案候选生成及其结果持久化。
- R Plumber 绘图服务及生产部署。
- 审计日志、账户停用/匿名化、备份恢复和公网安全加固。

旧版数据缓存不会自动进入 PostgreSQL。导入历史数据前，需要确认来源、授权、字段映射、去重策略、备份与回滚方式。
