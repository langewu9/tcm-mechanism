# 当前架构

本说明只记录当前运行中的组件及其连接方式。

## 服务关系

```text
浏览器
  └─ React + Vite（web/，本机端口 5173）
       └─ /api、/accounts、/django-admin → Django REST Framework（python_app/，端口 8020）
            ├─ 原 SQLite 数据库（本机恢复配置）或 PostgreSQL（开发/生产配置）
            ├─ Redis → Celery 普通分析队列和 R 图表队列
            └─ 私有容器网络 → R Plumber 图表服务（r_viz/，端口 8001）
```

前端开发代理配置在 `web/vite.config.ts`。R 服务不向宿主机发布端口，也不直接访问业务数据库或用户上传目录。图表任务由 Celery R worker 转发经校验的绘图请求。

## 本机原数据库配置

- 一键入口：`start-all-services.cmd`。
- Docker 配置：`deploy/compose.original-sqlite.yml`。
- 业务库：`python_app/var/qa.sqlite3`；整个 `python_app/var/` 目录以绑定卷挂载，旁置文件和媒体目录随库保留。
- 数据源文件目录：`var/source-databases/`，容器内只读挂载。
- 前端由本机 Node/Vite 启动；后端、Redis、R 服务及分析 worker 由 Docker 启动。

启动器先检查原数据库存在性，再等待 Docker、API、R 和两个任务队列健康。原库配置只检查已有主库迁移状态；不初始化空库、不重建主库、不运行主库迁移。

## PostgreSQL 与生产配置

`deploy/compose.python.yml` 提供隔离的 PostgreSQL 开发环境；它使用独立数据卷，不替代本机原 SQLite 配置。`deploy/compose.production.yml` 配置 PostgreSQL、Redis、Django/Gunicorn、Celery、R 服务及 Nginx。生产部署细节、密钥、TLS、对象存储和备份要求见 `deploy/README-production.md`。

## 数据边界

- `python_app/` 保存 Django 业务代码和迁移；真实研究数据库及媒体文件属于运行数据。
- `var/source-databases/` 中的来源文件按挂载配置提供给服务，不作为代码提交。
- `public/` 仅放品牌素材和已审核的公开演示图，不放真实患者资料、上传文件或数据库导出。
- `web/` 的 R 演示页使用 `r_viz/` 生成或仓库内授权的演示素材；演示数据与研究任务数据分开。

## 维护入口

- 原库启动与故障排查：`docs/Windows启动手册.md`、`docs/原数据库Docker启动说明.md`。
- 数据身份和物种说明：`docs/标准靶点主表与核验说明.md`、`docs/多数据库统一主表与兼容规范.md`、`docs/target-species-and-project-data-audit-2026-11-03.md`。
- R 图表接口和演示图库：`docs/r-visualization-contract.md`、`docs/R-demo-gallery.md`。
- 资料归档规则：`docs/research-retention.md`。
