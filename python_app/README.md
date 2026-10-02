# Python 主站（第一阶段）

这是与现有 Next.js 网站并行迁移的 Django 主站骨架。第一阶段交付登录/会话、管理后台、受用户隔离的医案与数据集 API，以及带来源版本的知识关系模型。现有 Next.js、FastAPI 和桌面程序暂不删除。

## 本地启动

要求 Python 3.12+。先在仓库根目录启动仅供本地开发的 PostgreSQL：

```powershell
docker compose -f deploy/compose.python.yml up -d postgres
```

然后在 `python_app` 目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8020
```

访问 `http://127.0.0.1:8020/`、`/admin/`、`/api/v1/` 和 `/api/docs/`。默认数据库配置只连接本机开发容器；生产环境必须替换数据库凭据和 `DJANGO_SECRET_KEY`，不要提交 `.env`。

## 第一阶段接口

- `GET /api/v1/health/`：检查 Django 与 PostgreSQL 连通状态。
- `GET /api/schema/`、`/api/docs/`：OpenAPI schema 与交互式接口文档。
- `/api/v1/datasets/`：当前登录用户的数据集元信息 CRUD；文件上传和对象存储尚未接入。
- `/api/v1/cases/`：当前登录用户的去标识化医案 CRUD。
- `/api/v1/analysis-tasks/`：当前用户的分析任务只读记录；Celery worker 尚未接入。
- `/api/v1/sources/`、`/entities/`、`/evidence/`：已启用数据源、规范实体和来源证据只读查询。

所有业务 API 默认要求登录。医案/数据集/任务通过服务端用户范围过滤；外部知识关系以 `SourceRelease` 和 `source_record_id` 留下版本及幂等键。医案内容字段应只接收去标识化文本。

## 本阶段边界

- 数据同步 connector、外部 API 定时更新和管理员同步控制台在下一阶段实现。
- 蛋白组学导入/QC/富集/PPI、医案候选生成与分析任务执行器尚未迁入。
- R Plumber 服务未部署；Python→R 的请求和产物 manifest 见 `docs/r-visualization-contract.md`。
- 本服务不复用或自动转换 `data_cache.db`；历史数据迁移前需先做数据清单、字段映射、授权核对和可回退备份。
- 生产部署、Redis/Celery、对象存储、审计日志及用户邀请流程不属于当前骨架，不能把本阶段视作生产就绪。
