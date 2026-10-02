# 部署说明

## 本地服务组合

推荐本地开发同时启动三个服务：

```bat
cd /d D:\MMDD\tcm_pharmacology_platform
npm run dev
```

```bat
cd /d D:\MMDD\tcm_pharmacology_platform
D:\mini\envs\py310\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

```bat
cd /d D:\MMDD\tcm_pharmacology_platform
start_biancang_server.bat
```

访问 Next 网站：

```text
http://127.0.0.1:3000
```

FastAPI 旧服务：

```text
http://127.0.0.1:8010
```

本地模型 OpenAI 兼容服务：

```text
http://127.0.0.1:8000/v1
```

## 数据库

开发环境默认使用 SQLite：

```bat
npx prisma generate
npx prisma db push
npm run prisma:seed
```

如果切换 PostgreSQL，将 `.env` 中的 `DATABASE_URL` 改为 PostgreSQL 连接串，再执行：

```bat
npm run prisma:deploy
npm run prisma:seed
```

## Docker 思路

原根目录 `Dockerfile` 保留为 FastAPI 服务镜像。Next 网站建议单独部署，或在容器编排中拆为：

- `web`: Next.js，端口 `3000`
- `api`: FastAPI，端口 `8010`
- `model`: BianCang OpenAI 兼容服务，端口 `8000`
- `db`: PostgreSQL，或使用挂载 SQLite 文件

ChEMBL 和 7B 模型体积较大，不建议复制进镜像，应通过卷挂载。

## Vercel

Next 站点可以部署到 Vercel，但本地 BianCang 模型和 FastAPI 服务需要有公网可访问地址，或保持为内网部署。

需要配置：

```text
DATABASE_URL
AUTH_SECRET
NEXT_PUBLIC_FASTAPI_BASE_URL
NEXT_PUBLIC_MODEL_BASE_URL
BIANCANG_MODEL
```

部署前执行：

```bat
npm run build
```
