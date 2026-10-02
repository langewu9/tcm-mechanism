# 岐黄中医药理智能平台

这是一个面向中医医案、方药、成分、靶点、基因和通路分析的全栈网站。项目保留原 FastAPI 数据/模型服务，并新增 Next.js + TypeScript + Tailwind CSS + Prisma 的生产化 Web 应用。

## 技术栈

- 前端/全栈站点：Next.js、TypeScript、Tailwind CSS、Recharts、Lucide
- 数据库：Prisma ORM，默认 SQLite，后续可切换 PostgreSQL
- 后端服务：FastAPI，继续提供本地药理数据、ChEMBL、Qwen/BianCang 接口
- 模型：QLUNLP/BianCang-Qwen2.5-7B-Instruct，本地 OpenAI 兼容服务
- 上传：CSV、XLS、XLSX
- 导出：分析结果 CSV、PDF

## Python 主站迁移（进行中）

按新的技术路线，仓库新增 `python_app/` 作为 Django 5.2 + Django REST Framework + PostgreSQL 的独立应用，当前已包含登录/管理入口、用户隔离的医案与数据集 API、分析任务记录、数据源/版本/证据模型及 OpenAPI 文档。它与现有 Next.js、FastAPI 服务并行运行，尚未替换旧页面，也未迁移历史数据库。

第一阶段启动方式、接口边界和未完成功能见 [`python_app/README.md`](python_app/README.md)；总体路线见 [`docs/技术栈与阶段实施计划.md`](docs/技术栈与阶段实施计划.md)，Python–R 图表接口草案见 [`docs/r-visualization-contract.md`](docs/r-visualization-contract.md)。目前外部数据 connector、Celery 分析 worker、文件上传、蛋白组学全链路、医案候选分析和 R 图表服务仍是后续阶段，不应把模型骨架视为已经动态更新或生产就绪。

## 目录

- `src/`: Next.js 全栈网站、页面、API Routes、组件和业务库
- `prisma/`: Prisma schema、迁移 SQL、seed 脚本、SQLite 开发库
- `backend/`: 原 FastAPI 服务
- `tools/`: BianCang 模型下载和 OpenAI 兼容服务脚本
- `frontend/`: 原静态前端，仍可由 FastAPI 服务访问
- `TCMPS/`: 医案与网页分析原始材料
- `manual_render/`: 手册渲染材料，当前按要求保留不移动

## 本地启动

首次安装依赖：

```bat
cd /d D:\MMDD\tcm_pharmacology_platform
npm install --cache .\.npm-cache
npx prisma generate
npx prisma db push
npm run prisma:seed
npm run db:sync -- "本地药理缓存库" 10000
```

第三个参数为本次最大读取行数；使用 `--all` 可从持久化游标继续同步到源表末尾。同步可重复运行，实体和关联关系按唯一键幂等更新。API 同步请求传入 `{"reset":true}` 可将游标归零并全量重扫。

启动 Next 全栈网站：

```bat
cd /d D:\MMDD\tcm_pharmacology_platform
npm run dev
```

访问：

```text
http://127.0.0.1:3000
```

默认账号：

```text
管理员：admin@qihuang.local / Admin123!
研究员：user@qihuang.local / User123!
```

生产构建：

```bat
npm run build
npm run start
```

## FastAPI 与本地模型

启动 FastAPI 数据服务：

```bat
cd /d D:\MMDD\tcm_pharmacology_platform
D:\mini\envs\py310\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

启动 BianCang 模型服务：

```bat
cd /d D:\MMDD\tcm_pharmacology_platform
start_biancang_server.bat
```

模型服务地址：

```text
http://127.0.0.1:8000/v1
```

Next 站点右下角的模型助手会调用 `/api/assistant`，再代理到 FastAPI 的 `/api/scientist/hypothesis`。

## 功能模块

- 首页：按需求文档建立统一视觉入口
- 登录/注册/退出：Cookie 会话、PBKDF2 密码哈希、角色字段
- 工作台：数据集、医案、任务和知识库统计
- 数据管理：CSV/Excel 上传、列表、删除、API 查询
- 医案管理：医案新增、列表、删除
- 分析流程：医案或文本输入，生成证候-方剂-药物-成分-靶点-基因-通路链路
- 可视化：知识库规模图表和分析网络图
- 管理后台：用户、数据集、分析任务总览
- API 接入：Next.js 代理 FastAPI，集中测试数据源、ChEMBL、Qwen/BianCang 与 AI Scientist 链路
- 模型助手：全站浮动 BianCang/Qwen 问答入口

## 关键 API

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/dashboard`
- `GET/POST /api/datasets`
- `GET/DELETE /api/datasets/[id]`
- `GET/POST /api/cases`
- `DELETE /api/cases/[id]`
- `GET/POST /api/analysis/tasks`
- `GET /api/analysis/results/[id]`
- `GET /api/analysis/results/[id]/export/csv`
- `GET /api/analysis/results/[id]/export/pdf`
- `GET /api/admin/users`
- `GET /api/admin/datasets`
- `GET /api/admin/tasks`
- `POST /api/assistant`
- `GET/POST /api/admin/database-sources`
- `POST /api/admin/database-sources/[id]/test`
- `POST /api/admin/database-sources/[id]/sync`
- `GET /api/integrations/status`
- `POST /api/integrations/test`

## API 接入控制台

登录 Next 全栈网站后访问：

```text
http://127.0.0.1:3000/api-integration
```

该页面会通过 Next API Routes 真实代理调用 FastAPI：

- 健康状态：`/api/health`
- 数据源状态：`/api/sources`
- Qwen/BianCang 状态：`/api/qwen/status`、`/api/qwen/models`、`/api/qwen/test`
- 证据检索：疾病、中药、成分检索
- 验证工具：靶点交集、成分比对
- ChEMBL：本地分子检索
- AI Scientist：研究计划生成样例

## 环境变量

复制 `.env.example` 到 `.env` 后按环境修改：

```text
DATABASE_URL="file:./dev.db"
AUTH_SECRET="change-this-to-a-long-random-string"
NEXT_PUBLIC_FASTAPI_BASE_URL="http://127.0.0.1:8010"
NEXT_PUBLIC_MODEL_BASE_URL="http://127.0.0.1:8000/v1"
BIANCANG_MODEL="QLUNLP/BianCang-Qwen2.5-7B-Instruct"
```

## 部署

更多部署说明见：

- `deploy/README.md`
- `deploy/FULLSTACK.md`

当前已完成本地验证：

- `npm run build` 通过
- `npx prisma generate` 通过
- `npx prisma db push` 通过
- `npm run prisma:seed` 通过
